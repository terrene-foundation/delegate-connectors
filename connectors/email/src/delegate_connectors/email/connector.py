# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""``EmailConnector`` — the shipped ``kailash.delegate.Connector`` for email.

Subclasses :class:`kailash.delegate.dispatch.Connector` DIRECTLY (ADR-1), NOT
``LegacyInvokeConnector`` (whose proxied ``read``/``write`` emit empty,
unverifiable receipts). Every receipt this connector produces is NON-EMPTY and
verifies under a real :class:`~kailash.delegate.verifier.Ed25519Verifier`.

Audited primitives:

- :meth:`write` — runs a zero-arg async thunk (the SMTP send) under audit and
  returns a :class:`SignedActionEnvelope` whose Ed25519 signature over the
  action's canonical bytes verifies under the connector's directory.
- :meth:`read` — runs a zero-arg async thunk (the IMAP fetch) under audit and
  returns ``(messages, AttestedReadReceipt)`` with a verifiable attestation.
- :meth:`authenticate` — resolves the dispatch identity's email to a
  ``Principal`` (unknown → fail-closed ``ConnectorAuthenticationError``).
- :meth:`invoke` — the dispatch hot-path entry; sends and returns a
  ``ConnectorInvocationResult``.

Trust properties: ``auth_verifier`` returns the supplied ``Ed25519Verifier``.
``ledger`` / ``revocation`` return Protocol-satisfying deterministic adapters
(in-memory append-only ledger; never-revoked channel) — these are dumb data
endpoints, NOT custom trust primitives (the SDK ships only the Protocols, not
concretes). Signing / verification stays with the shipped Ed25519 stack.

No credential ever enters a log line or an audit payload.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate.dispatch import (
    AttestedReadReceipt,
    Connector,
    ConnectorInvocationResult,
    Principal,
    SignedActionEnvelope,
)
from kailash.delegate.types import DelegateIdentity
from kailash.delegate.envelope import DelegateConstraintEnvelope
from kailash.delegate.verifier import Ed25519Verifier
from kailash.delegate import DelegateEventType
from kailash.trust._json import canonical_json_dumps

from delegate_connectors.email.directory import (
    EmailPrincipalResolver,
    UnknownSenderDisposition,
)
from delegate_connectors.email.imap import ImapTransport, InboundMessage
from delegate_connectors.email.smtp import OutboundMessage, SmtpTransport

logger = logging.getLogger(__name__)

__all__ = [
    "EmailConnector",
    "ConnectorAuthenticationError",
    "InMemoryKnowledgeLedger",
    "NeverRevokedChannel",
]


class ConnectorAuthenticationError(PermissionError):
    """Raised by :meth:`EmailConnector.authenticate` for an unknown sender.

    Fail-closed: an unresolved address maps to the closed-enum ``Reject``
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


class NeverRevokedChannel:
    """Protocol-satisfying revocation channel (``RevocationChannel``).

    v0 has no revocation source wired, so every principal is live. A
    deterministic data endpoint (always ``False``), NOT a mock. A real
    revocation backend binds structurally in a later shard without changing
    the connector contract.
    """

    def is_revoked(self, delegate_id: str) -> bool:
        return False


class EmailConnector(Connector):
    """Email connector implementing the shipped ``Connector`` ABC.

    Args:
        smtp: SMTP outbound transport.
        imap: IMAP inbound transport.
        resolver: address → Principal resolver (exact-match v0).
        signing_key: the connector's Ed25519 private key. The matching public
            key MUST be registered in the directory the ``verifier`` consults,
            keyed on the dispatch identity's ``delegate_id``, so the receipts
            this connector signs verify under that ``verifier``.
        verifier: the ``Ed25519Verifier`` returned by :attr:`auth_verifier`.
        tenant_id: the tenant the connector operates under (echoed as
            ``tenant_id_observed``; ``None`` for global).
    """

    connector_id = "delegate-connector-email"
    connector_kind = "email"
    requires_capabilities = frozenset({"email.send"})

    def __init__(
        self,
        *,
        smtp: SmtpTransport,
        imap: ImapTransport,
        resolver: EmailPrincipalResolver,
        signing_key: Ed25519PrivateKey,
        verifier: Ed25519Verifier,
        tenant_id: str | None = None,
    ) -> None:
        if not isinstance(smtp, SmtpTransport):
            raise TypeError(f"smtp MUST be an SmtpTransport; got {type(smtp).__name__}")
        if not isinstance(imap, ImapTransport):
            raise TypeError(f"imap MUST be an ImapTransport; got {type(imap).__name__}")
        if not isinstance(resolver, EmailPrincipalResolver):
            raise TypeError(
                f"resolver MUST be an EmailPrincipalResolver; got {type(resolver).__name__}"
            )
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise TypeError(
                f"signing_key MUST be an Ed25519PrivateKey; got {type(signing_key).__name__}"
            )
        if not isinstance(verifier, Ed25519Verifier):
            raise TypeError(
                f"verifier MUST be an Ed25519Verifier; got {type(verifier).__name__}"
            )
        self._smtp = smtp
        self._imap = imap
        self._resolver = resolver
        self._signing_key = signing_key
        self._verifier = verifier
        self._tenant_id = tenant_id
        self._ledger = InMemoryKnowledgeLedger()
        self._revocation = NeverRevokedChannel()

    # ── Trust properties (3) ────────────────────────────────────────────

    @property
    def auth_verifier(self) -> Ed25519Verifier:
        return self._verifier

    @property
    def ledger(self) -> InMemoryKnowledgeLedger:
        return self._ledger

    @property
    def revocation(self) -> NeverRevokedChannel:
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
        ``^[a-zA-Z0-9_-]+$`` and so cannot carry an email address (see
        ``workspaces/email/journal/0006-DISCOVERY-*``); the literal email lives
        on the message payload instead. Unknown identity →
        ``ConnectorAuthenticationError`` (fail-closed Reject).
        """
        outcome = self._resolver.resolve_delegate_id(str(identity.delegate_id))
        if not outcome.accepted or outcome.principal is None:
            logger.info(
                "email.authenticate.reject",
                extra={"disposition": UnknownSenderDisposition.REJECT.value},
            )
            raise ConnectorAuthenticationError(
                "email sender did not resolve to a known principal; "
                "disposition=Reject (fail-closed)"
            )
        logger.info(
            "email.authenticate.accept",
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

        ``action`` is a zero-arg async thunk wrapping the SMTP send. Its result
        is canonicalized, Ed25519-signed, and returned as a NON-EMPTY
        ``SignedActionEnvelope`` that verifies under the connector's verifier.
        """
        result_obj = await action()
        payload = _as_payload(result_obj)
        canonical_bytes = canonical_json_dumps(payload).encode("utf-8")
        signature = self._sign(canonical_bytes)
        self._ledger.record(DelegateEventType.EXTERNAL_SIDE_EFFECT.value, payload)
        logger.info(
            "email.write.signed",
            extra={"signer_delegate_id": str(identity.delegate_id)},
        )
        return SignedActionEnvelope(
            action_id=uuid.uuid4(),
            canonical_bytes=canonical_bytes,
            signature=signature,
            signer_delegate_id=str(identity.delegate_id),
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

        ``query`` is a zero-arg async thunk wrapping the IMAP fetch. The fetched
        value is canonicalized, Ed25519-signed, and returned with a NON-EMPTY
        ``AttestedReadReceipt`` that verifies under the connector's verifier.
        """
        value = await query()
        manifest = _read_manifest(value)
        canonical_bytes = canonical_json_dumps(manifest).encode("utf-8")
        attestation = self._sign(canonical_bytes)
        self._ledger.record(DelegateEventType.CONSTRAINT_DECISION.value, manifest)
        logger.info(
            "email.read.attested",
            extra={"attester_delegate_id": str(identity.delegate_id)},
        )
        receipt = AttestedReadReceipt(
            read_id=uuid.uuid4(),
            canonical_bytes=canonical_bytes,
            attestation=attestation,
            attester_delegate_id=str(identity.delegate_id),
            observed_at=datetime.now(timezone.utc),
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

        ``input_payload`` carries ``{sender, to, subject, body}``. The send is
        executed via the audited :meth:`write` path (so it produces a verifiable
        envelope as a side effect), and the invocation result reports the
        external side effect for the dispatch surface's audit chain.
        """
        message = OutboundMessage(
            sender=input_payload["sender"],
            recipient=input_payload["to"],
            subject=input_payload.get("subject", ""),
            body=input_payload.get("body", ""),
        )

        async def _send() -> dict[str, Any]:
            send_result = await self._smtp.send(message)
            return {
                "message_id": send_result.message_id,
                "accepted": send_result.accepted,
                "recipient": send_result.recipient,
            }

        envelope_result = await self.write(_send, identity=identity, envelope=envelope)
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

    A list of :class:`InboundMessage` is summarized as message ids + count
    (no body bytes enter the audited canonical payload). Other shapes fall back
    to a json-native value / repr.
    """
    if isinstance(value, list) and all(isinstance(m, InboundMessage) for m in value):
        return {
            "count": len(value),
            "message_ids": [m.message_id for m in value],
        }
    return {"value": value if _json_native(value) else repr(value)}


def _json_native(obj: Any) -> bool:
    return isinstance(obj, (dict, list, str, int, float, bool, type(None)))
