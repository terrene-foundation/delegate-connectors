# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — M1 (MED): invoke sent without authenticating.

Before this fix, `connector.invoke` went straight to send and never called
`self.authenticate(...)`, so the fail-closed unknown-sender `Reject` (surfaced
as `ConnectorAuthenticationError`) never ran on the dispatch hot path.

Fix: `invoke` calls `self.authenticate(identity, envelope)` at the TOP; an
unknown principal raises `ConnectorAuthenticationError` and NO SMTP send fires.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import DelegateIdentity, Ed25519Verifier, PrincipalDirectory
from kailash.delegate.dispatch import Principal
from kailash.delegate.envelope import DelegateConstraintEnvelope
from kailash.delegate.types import DelegateGenesisRecord
from kailash.trust.chain import AuthorityType, GenesisRecord
from kailash.trust.envelope import ConstraintEnvelope

from delegate_connectors.email.connector import (
    ConnectorAuthenticationError,
    EmailConnector,
)
from delegate_connectors.email.directory import EmailPrincipalResolver
from delegate_connectors.email.imap import ImapConfig, ImapTransport
from delegate_connectors.email.smtp import SmtpConfig, SmtpTransport

pytestmark = pytest.mark.regression


def _build():
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key().public_bytes_raw()
    known_id = uuid.uuid4()
    known_identity = DelegateIdentity(
        delegate_id=known_id,
        sovereign_ref="sovereign-1",
        role_binding_ref="rb-1",
        genesis_ref="g-1",
    )
    unknown_identity = DelegateIdentity(
        delegate_id=uuid.uuid4(),
        sovereign_ref="s",
        role_binding_ref="r",
        genesis_ref="g",
    )
    directory = PrincipalDirectory(
        identities=(known_identity, unknown_identity),
        verification_keys={
            known_id: pk,
            unknown_identity.delegate_id: pk,
        },
    )
    verifier = Ed25519Verifier(directory)
    # Resolver only knows the KNOWN principal — the unknown identity resolves to
    # Reject (fail-closed).
    resolver = EmailPrincipalResolver(
        {
            "alice@example.com": Principal(
                delegate_id=str(known_id), tenant_id="t1", claims={}
            )
        }
    )
    connector = EmailConnector(
        smtp=SmtpTransport(SmtpConfig(host="h", port=1025)),
        imap=ImapTransport(ImapConfig(host="h", port=1143)),
        resolver=resolver,
        signing_key=sk,
        verifier=verifier,
        tenant_id="t1",
    )
    genesis_block = GenesisRecord(
        id="gb",
        agent_id=str(known_id),
        authority_id="a",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    dgen = DelegateGenesisRecord(
        block=genesis_block, spec_version="0", capabilities=("email.send",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)
    return connector, known_identity, unknown_identity, envelope


@pytest.mark.asyncio
async def test_invoke_unknown_sender_rejects_and_does_not_send(monkeypatch):
    """An unknown principal raises ConnectorAuthenticationError; ZERO SMTP send."""
    connector, _known, unknown_identity, envelope = _build()
    sends: list = []

    async def recording_send(message):  # pragma: no cover - must NOT be called
        sends.append(message)
        raise AssertionError("SMTP send MUST NOT fire for an unknown sender")

    monkeypatch.setattr(connector._smtp, "send", recording_send)

    with pytest.raises(ConnectorAuthenticationError, match="Reject"):
        await connector.invoke(
            {
                "sender": "alice@example.com",
                "to": "bob@x.com",
                "subject": "Hi",
                "body": "yo",
            },
            identity=unknown_identity,
            envelope=envelope,
        )
    assert sends == [], "no SMTP send may occur for an unauthenticated sender"


@pytest.mark.asyncio
async def test_invoke_known_sender_still_authenticates_and_sends(monkeypatch):
    """A known principal passes authentication and the send proceeds."""
    from delegate_connectors.email.smtp import SendResult

    connector, known_identity, _unknown, envelope = _build()
    sends: list = []

    async def recording_send(message):
        sends.append(message)
        return SendResult(
            message_id=message.message_id,
            accepted=True,
            recipient=message.recipient,
            server_response="250 OK",
        )

    monkeypatch.setattr(connector._smtp, "send", recording_send)

    result = await connector.invoke(
        {
            "sender": "alice@example.com",
            "to": "bob@x.com",
            "subject": "Hi",
            "body": "yo",
        },
        identity=known_identity,
        envelope=envelope,
    )
    assert result.external_side_effect is True
    assert len(sends) == 1, "the send proceeds once authentication passes"
