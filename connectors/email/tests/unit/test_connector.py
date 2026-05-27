# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for EmailConnector.

The external transport is stubbed ONLY at the SDK boundary (the zero-arg async
thunk passed to read/write, and the connector's own smtp.send for the invoke
path). The Connector / runtime CONTRACT itself is never mocked: the connector
is the real subclass, receipts are signed with a real Ed25519 key, and they are
verified with the real shipped Ed25519Verifier.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import (
    DelegateIdentity,
    Ed25519Verifier,
    PrincipalDirectory,
)
from kailash.delegate.dispatch import (
    AttestedReadReceipt,
    Connector,
    ConnectorInvocationResult,
    Principal,
    SignedActionEnvelope,
)
from kailash.delegate.envelope import DelegateConstraintEnvelope
from kailash.delegate.types import DelegateGenesisRecord
from kailash.trust.chain import AuthorityType, GenesisRecord
from kailash.trust.envelope import ConstraintEnvelope

from delegate_connectors.email.connector import (
    ConnectorAuthenticationError,
    EmailConnector,
)
from delegate_connectors.email.directory import EmailPrincipalResolver
from delegate_connectors.email.imap import ImapConfig, ImapTransport, InboundMessage
from delegate_connectors.email.smtp import SendResult, SmtpConfig, SmtpTransport

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fixture():
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key().public_bytes_raw()
    delegate_id = uuid.uuid4()
    identity = DelegateIdentity(
        delegate_id=delegate_id,
        sovereign_ref="sovereign-1",
        role_binding_ref="rb-1",
        genesis_ref="g-1",
    )
    directory = PrincipalDirectory(
        identities=(identity,), verification_keys={delegate_id: pk}
    )
    verifier = Ed25519Verifier(directory)
    resolver = EmailPrincipalResolver(
        {
            "alice@example.com": Principal(
                delegate_id=str(delegate_id), tenant_id="t1", claims={}
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
        agent_id=str(delegate_id),
        authority_id="a",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    dgen = DelegateGenesisRecord(
        block=genesis_block, spec_version="0", capabilities=("email.send",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)
    return {
        "connector": connector,
        "identity": identity,
        "verifier": verifier,
        "envelope": envelope,
        "delegate_id": delegate_id,
    }


async def test_connector_satisfies_abc(fixture):
    conn = fixture["connector"]
    assert isinstance(conn, Connector)
    assert EmailConnector.__abstractmethods__ == frozenset()


async def test_trust_properties_return_concretes_never_raise(fixture):
    conn = fixture["connector"]
    assert isinstance(conn.auth_verifier, Ed25519Verifier)
    # ledger + revocation must not raise on access (the LegacyInvokeConnector
    # failure mode this connector exists to avoid).
    assert conn.ledger is not None
    assert conn.revocation.is_revoked("anyone") is False


async def test_authenticate_known_identity_returns_principal(fixture):
    conn, identity = fixture["connector"], fixture["identity"]
    principal = await conn.authenticate(identity, fixture["envelope"])
    assert principal.delegate_id == str(fixture["delegate_id"])


async def test_authenticate_unknown_identity_is_reject(fixture):
    conn, envelope = fixture["connector"], fixture["envelope"]
    unknown = DelegateIdentity(
        delegate_id=uuid.uuid4(),
        sovereign_ref="s",
        role_binding_ref="r",
        genesis_ref="g",
    )
    with pytest.raises(ConnectorAuthenticationError, match="Reject"):
        await conn.authenticate(unknown, envelope)


async def test_write_returns_non_empty_verifiable_envelope(fixture):
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return {"message_id": "<m@x>", "accepted": True, "recipient": "bob@x.com"}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    assert isinstance(envelope, SignedActionEnvelope)
    assert envelope.signature  # NON-EMPTY (LegacyInvokeConnector emits b"")
    assert envelope.canonical_bytes
    assert verifier.verify(
        envelope.canonical_bytes, envelope.signature, str(fixture["delegate_id"])
    )


async def test_read_returns_non_empty_verifiable_receipt(fixture):
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return [
            InboundMessage(
                from_addr="a@b.com",
                to_addr="c@d.com",
                subject="Hi",
                body="hello",
                message_id="<m1@x>",
            )
        ]

    messages, receipt = await conn.read(
        thunk, identity=identity, envelope=fixture["envelope"]
    )
    assert len(messages) == 1
    assert isinstance(receipt, AttestedReadReceipt)
    assert receipt.attestation  # NON-EMPTY
    assert receipt.canonical_bytes
    assert verifier.verify(
        receipt.canonical_bytes, receipt.attestation, str(fixture["delegate_id"])
    )


async def test_write_receipt_does_not_verify_under_wrong_key(fixture):
    """A receipt signed by this connector MUST NOT verify under a foreign key."""
    conn, identity = fixture["connector"], fixture["identity"]

    async def thunk():
        return {"sent": True}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    # A directory with a DIFFERENT key for the same delegate_id rejects.
    foreign_sk = Ed25519PrivateKey.generate()
    foreign_dir = PrincipalDirectory(
        identities=(identity,),
        verification_keys={
            fixture["delegate_id"]: foreign_sk.public_key().public_bytes_raw()
        },
    )
    foreign_verifier = Ed25519Verifier(foreign_dir)
    assert not foreign_verifier.verify(
        envelope.canonical_bytes, envelope.signature, str(fixture["delegate_id"])
    )


async def test_invoke_returns_connector_invocation_result(fixture, monkeypatch):
    conn, identity = fixture["connector"], fixture["identity"]

    async def fake_send(message):
        return SendResult(
            message_id=message.message_id,
            accepted=True,
            recipient=message.recipient,
            server_response="250 OK",
        )

    monkeypatch.setattr(conn._smtp, "send", fake_send)
    result = await conn.invoke(
        {
            "sender": "alice@example.com",
            "to": "bob@x.com",
            "subject": "Hi",
            "body": "yo",
        },
        identity=identity,
        envelope=fixture["envelope"],
    )
    assert isinstance(result, ConnectorInvocationResult)
    assert result.external_side_effect is True
    assert result.tenant_id_observed == "t1"
    assert result.payload["accepted"] is True
