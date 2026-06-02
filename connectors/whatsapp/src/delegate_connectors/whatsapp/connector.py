# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""``WhatsAppConnector`` — the shipped ``kailash.delegate.Connector`` for WhatsApp.

Subclasses :class:`kailash.delegate.dispatch.Connector` DIRECTLY (WA-ADR-1, the
mirror of the slack / telegram decision), NOT ``LegacyInvokeConnector``
(whose proxied ``read`` / ``write`` emit empty, unverifiable receipts). Every
receipt this connector produces is NON-EMPTY and verifies under a real
:class:`~kailash.delegate.verifier.Ed25519Verifier`.

Audited primitives:

- :meth:`write` — runs a zero-arg async thunk (the Cloud API ``/messages``
  POST) under audit and returns a :class:`SignedActionEnvelope` whose Ed25519
  signature over the action's canonical bytes verifies under the connector's
  directory. The recipient is PII-redacted (to a ``wa:<8-hex>`` token via
  :func:`~delegate_connectors.whatsapp.redaction.redact_phone`) BEFORE the
  signed canonical bytes are built — the raw ``wa_id`` / phone never lands in
  an audit payload or a ledger record.
- :meth:`read` — runs a zero-arg async thunk (a one-shot drain of the
  in-process ingest buffer fed by the verified-webhook path) under audit and
  returns ``(messages, AttestedReadReceipt)`` with a verifiable attestation.
  Only message ids + a count enter the signed manifest — message bodies and
  sender ``wa_id``s never appear in the audited canonical payload.
- :meth:`authenticate` — resolves the dispatch identity's ``delegate_id`` to a
  ``Principal`` via the resolver (unknown → fail-closed
  :class:`ConnectorAuthenticationError`).
- :meth:`invoke` — the dispatch hot-path entry. Authenticates FIRST (so an
  unknown sender raises ``ConnectorAuthenticationError`` BEFORE any Cloud API
  call fires); then runs the template / service-window pre-flight ``Reject``
  gate (free-form outside the open 24h window → ``Reject``; un-approved
  template → ``Reject``); then dispatches via the audited :meth:`write` path
  and returns a ``ConnectorInvocationResult``.

Trust properties: ``auth_verifier`` returns the supplied ``Ed25519Verifier``.
``ledger`` returns a Protocol-satisfying deterministic in-memory append-only
adapter. ``revocation`` returns the host's production
:class:`~delegate_connectors_host.revocation.ProductionRevocationChannel`
(``default_revocation_channel()``) — a fail-closed, signed-denylist channel, NOT
the deleted unconditional-``False`` placeholder. Signing / verification stays
with the shipped Ed25519 stack.

Startup gate: the constructor calls :meth:`RedactionConfig.from_env` so an
installation missing ``WHATSAPP_PII_HMAC_KEY`` REFUSES to start. The
:func:`redact_phone` runtime path stays fail-soft (returns the grep-able
sentinel on a transient missing-key glitch); the constructor gate prevents the
*systematic* missing-key case where every audit payload would be filled with
the sentinel.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import DelegateEventType
from kailash.delegate.dispatch import (
    AttestedReadReceipt,
    Connector,
    ConnectorInvocationResult,
    Principal,
    RevocationChannel,
    SignedActionEnvelope,
)
from kailash.delegate.envelope import DelegateConstraintEnvelope
from kailash.delegate.types import DelegateIdentity
from kailash.delegate.verifier import Ed25519Verifier

from delegate_connectors_host.revocation import default_revocation_channel
from delegate_connectors_host.signing_bytes import (
    build_action_signing_bytes,
    build_read_signing_bytes,
    verify_action_envelope,
    verify_read_receipt,
)

from delegate_connectors.whatsapp.cloud_api import (
    OutboundMessage,
    WhatsAppCloudApi,
)
from delegate_connectors.whatsapp.directory import (
    UnknownSenderDisposition,
    WhatsAppPrincipalResolver,
)
from delegate_connectors.whatsapp.redaction import (
    RedactionConfig,
    redact_phone,
)
from delegate_connectors.whatsapp.templates import TemplateGate
from delegate_connectors.whatsapp.webhook import InboundMessage, WebhookIngest

logger = logging.getLogger(__name__)

__all__ = [
    "WhatsAppConnector",
    "ConnectorAuthenticationError",
    "InMemoryKnowledgeLedger",
    "build_action_signing_bytes",
    "build_read_signing_bytes",
    "verify_action_envelope",
    "verify_read_receipt",
]


class ConnectorAuthenticationError(PermissionError):
    """Raised by :meth:`WhatsAppConnector.authenticate` for an unknown sender.

    Fail-closed: an unresolved ``delegate_id`` maps to the closed-enum
    ``Reject`` disposition, surfaced as this typed error rather than a silent
    ``None``. On the ``invoke`` hot path this error propagates BEFORE any
    Cloud API send fires — the unknown-sender Reject is enforced on the
    dispatch hot path, not just the standalone ``authenticate`` call.
    """


class InMemoryKnowledgeLedger:
    """Protocol-satisfying in-memory ledger (``KnowledgeLedger``).

    A deterministic data endpoint, NOT a mock: append-only, inspectable. The
    SDK ships the ``KnowledgeLedger`` Protocol but no concrete backend, so
    the connector binds this minimal in-memory adapter. Records never carry
    credentials (the connector forwards only ``event_type`` + the
    PII-redacted payload — never the access token, never the raw recipient).
    """

    def __init__(self) -> None:
        self._records: list[tuple[str, dict[str, Any]]] = []

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        self._records.append((event_type, dict(payload)))

    @property
    def records(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple(self._records)


class WhatsAppConnector(Connector):
    """WhatsApp connector implementing the shipped ``Connector`` ABC.

    Args:
        cloud_api: Cloud API transport (``/messages`` POST).
        ingest: webhook ingest buffer; ``read`` drains it.
        resolver: WhatsApp principal resolver (dual-keyed: phone + delegate_id).
        template_gate: pre-flight template / service-window Reject gate.
        signing_key: the connector's Ed25519 private key. The matching public
            key MUST be registered in the directory the ``verifier`` consults,
            keyed on the dispatch identity's ``delegate_id``, so the receipts
            this connector signs verify under that ``verifier``.
        verifier: the ``Ed25519Verifier`` returned by :attr:`auth_verifier`.
        tenant_id: the tenant the connector operates under (echoed as
            ``tenant_id_observed``; ``None`` for global).

    Startup gate (binding): the constructor invokes
    :meth:`RedactionConfig.from_env` so an installation missing
    ``WHATSAPP_PII_HMAC_KEY`` REFUSES to start (loud
    :class:`RedactionConfigError`). The per-message :func:`redact_phone` call
    stays fail-soft (sentinel on transient miss); the constructor gate
    prevents the *systematic* missing-key case.
    """

    connector_id = "delegate-connector-whatsapp"
    connector_kind = "whatsapp"
    requires_capabilities = frozenset({"whatsapp.send"})

    def __init__(
        self,
        *,
        cloud_api: WhatsAppCloudApi,
        ingest: WebhookIngest,
        resolver: WhatsAppPrincipalResolver,
        template_gate: TemplateGate,
        signing_key: Ed25519PrivateKey,
        verifier: Ed25519Verifier,
        tenant_id: str | None = None,
    ) -> None:
        if not isinstance(
            cloud_api, WhatsAppCloudApi
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "cloud_api MUST be a WhatsAppCloudApi; got "
                f"{type(cloud_api).__name__}"
            )
        if not isinstance(
            ingest, WebhookIngest
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "ingest MUST be a WebhookIngest; got " f"{type(ingest).__name__}"
            )
        if not isinstance(
            resolver, WhatsAppPrincipalResolver
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "resolver MUST be a WhatsAppPrincipalResolver; got "
                f"{type(resolver).__name__}"
            )
        if not isinstance(
            template_gate, TemplateGate
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "template_gate MUST be a TemplateGate; got "
                f"{type(template_gate).__name__}"
            )
        if not isinstance(
            signing_key, Ed25519PrivateKey
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "signing_key MUST be an Ed25519PrivateKey; got "
                f"{type(signing_key).__name__}"
            )
        if not isinstance(
            verifier, Ed25519Verifier
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                f"verifier MUST be an Ed25519Verifier; got "
                f"{type(verifier).__name__}"
            )
        # Startup-loud PII-HMAC-key gate (todo 15 contract): refuse to
        # construct if WHATSAPP_PII_HMAC_KEY is unset / empty. The runtime
        # `redact_phone` path stays fail-soft (sentinel); this gate closes
        # the systematic missing-key case where every audit row would carry
        # the sentinel silently.
        RedactionConfig.from_env()

        self._cloud_api = cloud_api
        self._ingest = ingest
        self._resolver = resolver
        self._template_gate = template_gate
        self._signing_key = signing_key
        self._verifier = verifier
        self._tenant_id = tenant_id
        self._ledger = InMemoryKnowledgeLedger()
        self._revocation = default_revocation_channel()

    # ── Trust properties (3) ────────────────────────────────────────────

    @property
    def auth_verifier(self) -> Ed25519Verifier:
        return self._verifier

    @property
    def ledger(self) -> InMemoryKnowledgeLedger:
        return self._ledger

    @property
    def revocation(self) -> RevocationChannel:
        return self._revocation

    # ── Internal signing helper ─────────────────────────────────────────

    def _sign(self, canonical_bytes: bytes) -> bytes:
        """Ed25519-sign canonical bytes; returns 64 raw signature bytes."""
        return self._signing_key.sign(canonical_bytes)

    # ── Primitives (4) ──────────────────────────────────────────────────

    async def authenticate(
        self,
        identity: DelegateIdentity,
        envelope: DelegateConstraintEnvelope,
    ) -> Principal:
        """Resolve the dispatch identity to a ``Principal``.

        The dispatch identity is resolved by its ``delegate_id``: the shipped
        ``DelegateIdentity`` validates its ref fields against
        ``^[a-zA-Z0-9_-]+$`` and so cannot carry a ``+``-prefixed phone
        number. The resolver's secondary ``delegate_id`` index is what
        ``authenticate`` consults; the literal phone number lives on the
        message payload (and is PII-redacted before audit bytes are built).
        Unknown identity → :class:`ConnectorAuthenticationError` (fail-closed
        ``Reject``).
        """
        outcome = self._resolver.resolve_delegate_id(str(identity.delegate_id))
        if not outcome.accepted or outcome.principal is None:
            logger.info(
                "whatsapp.authenticate.reject",
                extra={"disposition": UnknownSenderDisposition.REJECT.value},
            )
            raise ConnectorAuthenticationError(
                "whatsapp sender did not resolve to a known principal; "
                "disposition=Reject (fail-closed)"
            )
        logger.info(
            "whatsapp.authenticate.accept",
            extra={
                "disposition": UnknownSenderDisposition.ACCEPT.value,
                "delegate_id": outcome.principal.delegate_id,
            },
        )
        return outcome.principal

    async def write(
        self,
        action: Callable[[], Awaitable[Any]],
        *,
        identity: DelegateIdentity,
        envelope: DelegateConstraintEnvelope,
    ) -> SignedActionEnvelope:
        """Execute the write ``action`` thunk under audit; return a signed envelope.

        ``action`` is a zero-arg async thunk wrapping the Cloud API
        ``/messages`` POST. Its result is canonicalized (with the recipient
        PII-redacted to a ``wa:<8-hex>`` token BEFORE the signed canonical
        bytes are built), Ed25519-signed, and returned as a NON-EMPTY
        :class:`SignedActionEnvelope` that verifies under the connector's
        verifier.

        The raw ``wa_id`` / recipient phone NEVER enters the signed canonical
        bytes, the ledger record, or a log line — only the redacted token.
        """
        result_obj = await action()
        payload = _as_payload(result_obj)
        # Audit-payload PII redaction: rewrite any ``wa_id`` / ``to`` field
        # to its redacted token BEFORE the canonical bytes are built. This
        # is the binding floor — the audit payload NEVER carries raw PII.
        payload = _redact_payload(payload)
        signer_delegate_id = str(identity.delegate_id)
        action_id = uuid.uuid4()
        observed_at = datetime.now(timezone.utc)
        # Sign over the FULL receipt identity, not the bare payload: two
        # writes with an identical payload now produce DIFFERENT signed bytes
        # (distinct action_id + observed_at), and signer / action-id /
        # observed-at are bound.
        canonical_bytes = build_action_signing_bytes(
            payload,
            signer_delegate_id=signer_delegate_id,
            action_id=str(action_id),
            observed_at=observed_at.isoformat(timespec="microseconds"),
        )
        signature = self._sign(canonical_bytes)
        self._ledger.record(DelegateEventType.EXTERNAL_SIDE_EFFECT.value, payload)
        logger.info(
            "whatsapp.write.signed",
            extra={"signer_delegate_id": signer_delegate_id},
        )
        return SignedActionEnvelope(
            action_id=action_id,
            canonical_bytes=canonical_bytes,
            signature=signature,
            signer_delegate_id=signer_delegate_id,
            payload=payload,
        )

    async def read(
        self,
        query: Callable[[], Awaitable[Any]],
        *,
        identity: DelegateIdentity,
        envelope: DelegateConstraintEnvelope,
    ) -> tuple[Any, AttestedReadReceipt]:
        """Execute the read ``query`` thunk under audit; return (value, receipt).

        ``query`` is a zero-arg async thunk draining the in-process ingest
        buffer fed by the verified-webhook path. The drained messages are
        summarized to a count + message-id manifest (NEVER the message
        bodies, NEVER the raw sender ``wa_id``s), Ed25519-signed, and
        returned with a NON-EMPTY :class:`AttestedReadReceipt` that verifies
        under the connector's verifier.
        """
        value = await query()
        manifest = _read_manifest(value)
        attester_delegate_id = str(identity.delegate_id)
        read_id = uuid.uuid4()
        observed_at = datetime.now(timezone.utc)
        # Sign over the FULL receipt identity, not the bare manifest:
        # attester / read-id / observed-at are bound into the attestation.
        canonical_bytes = build_read_signing_bytes(
            manifest,
            attester_delegate_id=attester_delegate_id,
            read_id=str(read_id),
            observed_at=observed_at.isoformat(timespec="microseconds"),
        )
        attestation = self._sign(canonical_bytes)
        self._ledger.record(DelegateEventType.CONSTRAINT_DECISION.value, manifest)
        logger.info(
            "whatsapp.read.attested",
            extra={"attester_delegate_id": attester_delegate_id},
        )
        receipt = AttestedReadReceipt(
            read_id=read_id,
            canonical_bytes=canonical_bytes,
            attestation=attestation,
            attester_delegate_id=attester_delegate_id,
            observed_at=observed_at,
        )
        return value, receipt

    async def invoke(
        self,
        input_payload: dict[str, Any],
        *,
        identity: DelegateIdentity,
        envelope: DelegateConstraintEnvelope,
    ) -> ConnectorInvocationResult:
        """Dispatch hot-path entry: send the message described by ``input_payload``.

        ``input_payload`` carries ``{to, text}`` for a free-form message OR
        ``{to, template_name, template_language?}`` for a template send. The
        send is executed via the audited :meth:`write` path (so it produces a
        verifiable envelope as a side effect), and the invocation result
        reports the external side effect for the dispatch surface's audit
        chain.

        Order of operations (fail-closed):

        1. :meth:`authenticate` resolves the dispatch identity. Unknown
           identity → :class:`ConnectorAuthenticationError` propagates BEFORE
           any message construction or Cloud API send.
        2. Pre-flight :meth:`TemplateGate.check` fires. Free-form outside the
           24h customer-service window → :class:`OutsideServiceWindowError`.
           Un-approved template → :class:`TemplateNotApprovedError`. Either
           propagates BEFORE the audited write.
        3. Audited :meth:`write` builds the signed envelope; the Cloud API
           ``/messages`` POST is the auditable side effect.
        """
        # 1. Fail-closed auth: unknown identity -> ConnectorAuthenticationError,
        #    propagated before any message construction or Cloud API send.
        await self.authenticate(identity, envelope)

        to_raw = input_payload["to"]
        text = input_payload.get("text")
        template_name = input_payload.get("template_name")
        template_language = input_payload.get("template_language", "en_US")

        # 2. Construct the OutboundMessage FIRST — its __post_init__ runs the
        #    E.164 normalization + the exactly-one-of(text, template_name)
        #    contract. A construction failure raises MessageValidationError
        #    BEFORE the template gate or any Cloud API call.
        message = OutboundMessage(
            to=to_raw,
            text=text,
            template_name=template_name,
            template_language=template_language,
        )

        # 3. Pre-flight Reject gate (template / service-window). The gate
        #    consumes the bare-digit normalized recipient (which the
        #    OutboundMessage __post_init__ already produced) so the window
        #    lookup is symmetric with the inbound path's stored key.
        self._template_gate.check(message.to, template_name=template_name)

        async def _send() -> dict[str, Any]:
            send_result = await self._cloud_api.send(message)
            return {
                "wamid": send_result.wamid,
                "wa_id": send_result.wa_id,
                "to": message.to,
            }

        envelope_result = await self.write(_send, identity=identity, envelope=envelope)
        return ConnectorInvocationResult(
            payload=dict(envelope_result.payload),
            audit_events=(DelegateEventType.EXTERNAL_SIDE_EFFECT,),
            tenant_id_observed=self._tenant_id,
            external_side_effect=True,
        )


# ── Internal helpers ──────────────────────────────────────────────────


# Field names that may carry a raw recipient phone / wa_id. Any payload key
# matching this set has its value rewritten to the PII-redacted token before
# the canonical signing bytes are built (binding security floor: NO raw
# number ever enters audit bytes, ledger records, or log lines).
_PII_PAYLOAD_KEYS = frozenset({"to", "wa_id", "from", "recipient", "phone"})


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Rewrite PII-bearing fields to their redacted token.

    Walks the top-level payload keys; any key in :data:`_PII_PAYLOAD_KEYS`
    with a string value is rewritten to ``redact_phone(value)`` (a
    ``wa:<8-hex>`` token, or the grep-able sentinel on a redaction failure).
    Non-string values are left as-is — they cannot carry a raw E.164.
    """
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _PII_PAYLOAD_KEYS and isinstance(value, str) and value:
            out[key] = redact_phone(value)
        else:
            out[key] = value
    return out


def _as_payload(obj: Any) -> dict[str, Any]:
    """Coerce a write-action result into a JSON-canonical payload dict."""
    if isinstance(obj, dict):
        return obj
    return {"value": obj if _json_native(obj) else repr(obj)}


def _read_manifest(value: Any) -> dict[str, Any]:
    """Build a JSON-canonical read manifest from a drained ingest result.

    A list of :class:`InboundMessage` is summarized as count + message ids —
    NEVER message bodies, NEVER raw sender ``wa_id``s (those are already
    redacted on the dataclass anyway, but the manifest deliberately omits
    them). Other shapes fall back to a json-native value / repr.
    """
    if isinstance(value, list) and all(isinstance(m, InboundMessage) for m in value):
        return {
            "count": len(value),
            "message_ids": [m.message_id for m in value],
        }
    return {"value": value if _json_native(value) else repr(value)}


def _json_native(obj: Any) -> bool:
    return isinstance(obj, (dict, list, str, int, float, bool, type(None)))
