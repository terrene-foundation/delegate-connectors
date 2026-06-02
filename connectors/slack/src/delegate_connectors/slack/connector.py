# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""``SlackConnector`` — the shipped ``kailash.delegate.Connector`` for Slack.

Subclasses :class:`kailash.delegate.dispatch.Connector` DIRECTLY (ADR-1), NOT
``LegacyInvokeConnector`` (whose proxied ``read``/``write`` emit empty,
unverifiable receipts). Every receipt this connector produces is NON-EMPTY and
verifies under a real :class:`~kailash.delegate.verifier.Ed25519Verifier`.

Audited primitives:

- :meth:`write` — runs a zero-arg async thunk (the ``chat.postMessage`` call)
  under audit and returns a :class:`SignedActionEnvelope` whose Ed25519
  signature over the action's canonical bytes verifies under the connector's
  directory.
- :meth:`read` — runs a zero-arg async thunk (the ``conversations.history``
  fetch) under audit and returns ``(messages, AttestedReadReceipt)`` with a
  verifiable attestation. The audited manifest carries message ``ts`` ids +
  count only — NEVER message body bytes.
- :meth:`authenticate` — resolves the dispatch identity's ``delegate_id`` to a
  ``Principal`` (unknown → fail-closed ``ConnectorAuthenticationError``).
- :meth:`invoke` — the dispatch hot-path entry; authenticates FIRST (so an
  unknown sender's Reject fires BEFORE any Slack API call), then posts via
  the audited :meth:`write` path and returns a ``ConnectorInvocationResult``.

Trust properties: ``auth_verifier`` returns the supplied ``Ed25519Verifier``.
``ledger`` returns a Protocol-satisfying deterministic in-memory append-only
adapter. ``revocation`` returns the host's production
:class:`~delegate_connectors_host.revocation.ProductionRevocationChannel`
(``default_revocation_channel()``) — a fail-closed, signed-denylist channel, NOT
the deleted unconditional-``False`` placeholder. Signing / verification stays
with the shipped Ed25519 stack.

No credential ever enters a log line or an audit payload.

Signing helpers (``build_action_signing_bytes`` / ``build_read_signing_bytes`` /
``verify_action_envelope`` / ``verify_read_receipt``) are channel-agnostic in
shape — the email connector ships its own copy in the same shape, and the
canonical-json signing contract is shared via
:func:`kailash.trust._json.canonical_json_dumps`. Each connector re-implements
the boundary so receipt schemas can diverge per-connector without coupling.
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

from delegate_connectors.slack.directory import (
    SlackPrincipalResolver,
    UnknownSenderDisposition,
)
from delegate_connectors.slack.messages import (
    InboundSlackMessage,
    OutboundSlackMessage,
)
from delegate_connectors.slack.web_api import SlackTransport

logger = logging.getLogger(__name__)

__all__ = [
    "SlackConnector",
    "ConnectorAuthenticationError",
    "InMemoryKnowledgeLedger",
    "build_action_signing_bytes",
    "build_read_signing_bytes",
    "verify_action_envelope",
    "verify_read_receipt",
]


class ConnectorAuthenticationError(PermissionError):
    """Raised by :meth:`SlackConnector.authenticate` for an unknown sender.

    Fail-closed: an unresolved identity maps to the closed-enum ``Reject``
    disposition, surfaced as this typed error rather than a silent ``None``.
    """


class InMemoryKnowledgeLedger:
    """Protocol-satisfying in-memory ledger (``KnowledgeLedger``).

    A deterministic data endpoint, NOT a mock: append-only, inspectable. The
    SDK ships the ``KnowledgeLedger`` Protocol but no concrete backend, so the
    connector binds this minimal in-memory adapter. Records never carry
    credentials (the connector forwards only event_type + non-secret payload).
    """

    def __init__(self) -> None:
        self._records: list[tuple[str, dict[str, Any]]] = []

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        self._records.append((event_type, dict(payload)))

    @property
    def records(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        return tuple(self._records)


class SlackConnector(Connector):
    """Slack connector implementing the shipped ``Connector`` ABC.

    Args:
        transport: the :class:`SlackTransport` wrapping ``AsyncWebClient`` for
            both ``chat.postMessage`` and ``conversations.history``.
        resolver: delegate_id → Principal resolver (exact-match v0).
        signing_key: the connector's Ed25519 private key. The matching public
            key MUST be registered in the directory the ``verifier`` consults,
            keyed on the dispatch identity's ``delegate_id``, so the receipts
            this connector signs verify under that ``verifier``.
        verifier: the ``Ed25519Verifier`` returned by :attr:`auth_verifier`.
        tenant_id: the tenant the connector operates under (echoed as
            ``tenant_id_observed``; ``None`` for global).
    """

    connector_id = "delegate-connector-slack"
    connector_kind = "slack"
    requires_capabilities = frozenset({"slack.post"})

    def __init__(
        self,
        *,
        transport: SlackTransport,
        resolver: SlackPrincipalResolver,
        signing_key: Ed25519PrivateKey,
        verifier: Ed25519Verifier,
        tenant_id: str | None = None,
    ) -> None:
        if not isinstance(
            transport, SlackTransport
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                f"transport MUST be a SlackTransport; got {type(transport).__name__}"
            )
        if not isinstance(
            resolver, SlackPrincipalResolver
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                f"resolver MUST be a SlackPrincipalResolver; got {type(resolver).__name__}"
            )
        if not isinstance(
            signing_key, Ed25519PrivateKey
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                f"signing_key MUST be an Ed25519PrivateKey; got {type(signing_key).__name__}"
            )
        if not isinstance(
            verifier, Ed25519Verifier
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                f"verifier MUST be an Ed25519Verifier; got {type(verifier).__name__}"
            )
        self._transport = transport
        self._resolver = resolver
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

        The dispatch identity is resolved by its ``delegate_id`` (ADR-S2: the
        primary resolution key for cross-connector uniformity and stability
        across handle/workspace changes). The literal Slack id appears on the
        message payload, not the dispatch identity. Unknown identity →
        ``ConnectorAuthenticationError`` (fail-closed Reject).
        """
        outcome = self._resolver.resolve_delegate_id(str(identity.delegate_id))
        if not outcome.accepted or outcome.principal is None:
            logger.info(
                "slack.authenticate.reject",
                extra={"disposition": UnknownSenderDisposition.REJECT.value},
            )
            raise ConnectorAuthenticationError(
                "slack sender did not resolve to a known principal; "
                "disposition=Reject (fail-closed)"
            )
        logger.info(
            "slack.authenticate.accept",
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

        ``action`` is a zero-arg async thunk wrapping the ``chat.postMessage``
        call. Its result is canonicalized, Ed25519-signed, and returned as a
        NON-EMPTY ``SignedActionEnvelope`` that verifies under the connector's
        verifier.
        """
        result_obj = await action()
        payload = _as_payload(result_obj)
        signer_delegate_id = str(identity.delegate_id)
        action_id = uuid.uuid4()
        observed_at = datetime.now(timezone.utc)
        # Sign over the FULL receipt identity, not the bare payload: two writes
        # with an identical payload produce DIFFERENT signed bytes (distinct
        # action_id + observed_at), and signer/action-id/observed-at are bound.
        canonical_bytes = build_action_signing_bytes(
            payload,
            signer_delegate_id=signer_delegate_id,
            action_id=str(action_id),
            observed_at=observed_at.isoformat(timespec="microseconds"),
        )
        signature = self._sign(canonical_bytes)
        self._ledger.record(DelegateEventType.EXTERNAL_SIDE_EFFECT.value, payload)
        logger.info(
            "slack.write.signed",
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

        ``query`` is a zero-arg async thunk wrapping the
        ``conversations.history`` fetch. The fetched value is canonicalized,
        Ed25519-signed, and returned with a NON-EMPTY ``AttestedReadReceipt``
        that verifies under the connector's verifier. The audited manifest
        carries channel + message ``ts`` ids + count only — NEVER message body
        bytes.
        """
        value = await query()
        manifest = _read_manifest(value)
        attester_delegate_id = str(identity.delegate_id)
        read_id = uuid.uuid4()
        observed_at = datetime.now(timezone.utc)
        # Sign over the FULL receipt identity, not the bare manifest: attester /
        # read-id / observed-at are bound into the attestation.
        canonical_bytes = build_read_signing_bytes(
            manifest,
            attester_delegate_id=attester_delegate_id,
            read_id=str(read_id),
            observed_at=observed_at.isoformat(timespec="microseconds"),
        )
        attestation = self._sign(canonical_bytes)
        self._ledger.record(DelegateEventType.CONSTRAINT_DECISION.value, manifest)
        logger.info(
            "slack.read.attested",
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
        """Dispatch hot-path entry: post the message described by ``input_payload``.

        ``input_payload`` carries ``{channel, text}``. The post is executed via
        the audited :meth:`write` path (so it produces a verifiable envelope
        as a side effect), and the invocation result reports the external side
        effect for the dispatch surface's audit chain.

        Authentication runs FIRST: :meth:`authenticate` resolves the dispatch
        identity to a ``Principal`` and raises ``ConnectorAuthenticationError``
        (fail-closed ``Reject``) for an unknown sender. The error propagates and
        NO ``OutboundSlackMessage`` is constructed and NO ``chat.postMessage``
        call fires — the unknown-sender Reject is enforced on the dispatch hot
        path, not just the standalone :meth:`authenticate` call.
        """
        # Fail-closed gate: unknown identity -> ConnectorAuthenticationError,
        # propagated before any message construction or Slack API call.
        await self.authenticate(identity, envelope)

        message = OutboundSlackMessage(
            channel=input_payload["channel"],
            text=input_payload.get("text", ""),
        )

        async def _post() -> dict[str, Any]:
            post_result = await self._transport.post_message(message)
            return {
                "ok": post_result.ok,
                "ts": post_result.ts,
                "channel": post_result.channel,
            }

        envelope_result = await self.write(_post, identity=identity, envelope=envelope)
        return ConnectorInvocationResult(
            payload=dict(envelope_result.payload),
            audit_events=(DelegateEventType.EXTERNAL_SIDE_EFFECT,),
            tenant_id_observed=self._tenant_id,
            external_side_effect=True,
        )


def _as_payload(obj: Any) -> dict[str, Any]:
    """Coerce a write-action result into a JSON-canonical payload dict."""
    if isinstance(obj, dict):
        return obj
    return {"value": obj if _json_native(obj) else repr(obj)}


def _read_manifest(value: Any) -> dict[str, Any]:
    """Build a JSON-canonical read manifest from a fetch result.

    A list of :class:`InboundSlackMessage` is summarized as channel + message
    ``ts`` ids + count (no message body bytes enter the audited canonical
    payload). Other shapes fall back to a json-native value / repr.
    """
    if isinstance(value, list) and all(
        isinstance(m, InboundSlackMessage) for m in value
    ):
        channel = value[0].channel if value else ""
        return {
            "channel": channel,
            "count": len(value),
            "message_ts": [m.ts for m in value],
        }
    return {"value": value if _json_native(value) else repr(value)}


def _json_native(obj: Any) -> bool:
    return isinstance(obj, (dict, list, str, int, float, bool, type(None)))
