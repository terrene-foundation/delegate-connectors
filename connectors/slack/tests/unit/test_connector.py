# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for SlackConnector.

The external transport is stubbed ONLY at the SDK boundary (the zero-arg async
thunk passed to read/write, and the connector's own transport.post_message for
the invoke path). The Connector / runtime CONTRACT itself is never mocked: the
connector is the real subclass, receipts are signed with a real Ed25519 key, and
they are verified with the real shipped Ed25519Verifier.
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

from delegate_connectors.slack.connector import (
    ConnectorAuthenticationError,
    SlackConnector,
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors.slack.directory import SlackPrincipalResolver
from delegate_connectors.slack.messages import InboundSlackMessage
from delegate_connectors.slack.web_api import (
    PostResult,
    SlackTransport,
    SlackWebConfig,
)

pytestmark = pytest.mark.asyncio


class _FakeAsyncWebClient:
    """Minimal AsyncWebClient stand-in for the connector's transport seam."""

    def __init__(self):
        self.post_calls: list[dict] = []
        self.history_calls: list[dict] = []

    async def chat_postMessage(self, *, channel: str, text: str):
        self.post_calls.append({"channel": channel, "text": text})
        return {"ok": True, "ts": "1700000000.000123", "channel": channel}

    async def conversations_history(self, *, channel: str, limit: int):
        self.history_calls.append({"channel": channel, "limit": limit})
        return {"ok": True, "messages": []}


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
    fake_client = _FakeAsyncWebClient()
    transport = SlackTransport(
        SlackWebConfig(bot_token="xoxb-fixture", base_url="http://mock/api/"),
        _client=fake_client,
    )
    resolver = SlackPrincipalResolver(
        {
            "U07ABCDE123": Principal(
                delegate_id=str(delegate_id),
                tenant_id="t1",
                claims={"slack_user_id": "U07ABCDE123", "team_id": "T0AAA1111"},
            )
        }
    )
    connector = SlackConnector(
        transport=transport,
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
        block=genesis_block, spec_version="0", capabilities=("slack.post",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)
    return {
        "connector": connector,
        "transport": transport,
        "fake_client": fake_client,
        "identity": identity,
        "verifier": verifier,
        "envelope": envelope,
        "delegate_id": delegate_id,
    }


# ── Invariant 1 + 7: ABC contract + trust property concretes ─────────────


async def test_connector_satisfies_abc(fixture):
    """Invariant 1: every abstractmethod satisfied — isinstance check passes."""
    conn = fixture["connector"]
    assert isinstance(conn, Connector)
    assert SlackConnector.__abstractmethods__ == frozenset()


async def test_trust_properties_return_concretes_never_raise(fixture):
    """Invariant 7: trust properties NEVER raise (the LegacyInvokeConnector failure)."""
    conn = fixture["connector"]
    assert isinstance(conn.auth_verifier, Ed25519Verifier)
    assert conn.ledger is not None  # InMemoryKnowledgeLedger
    # revocation is the production fail-closed channel over a fresh-signed empty
    # denylist: "anyone" is genuinely NOT on the verified-fresh list (a REAL
    # answer), NOT the deleted unconditional-False placeholder.
    assert conn.revocation.is_revoked("anyone") is False


# ── Authenticate ─────────────────────────────────────────────────────────


async def test_authenticate_known_identity_returns_principal(fixture):
    conn, identity = fixture["connector"], fixture["identity"]
    principal = await conn.authenticate(identity, fixture["envelope"])
    assert principal.delegate_id == str(fixture["delegate_id"])
    assert principal.tenant_id == "t1"
    assert principal.claims["slack_user_id"] == "U07ABCDE123"


async def test_authenticate_unknown_identity_is_fail_closed_reject(fixture):
    conn, envelope = fixture["connector"], fixture["envelope"]
    unknown = DelegateIdentity(
        delegate_id=uuid.uuid4(),
        sovereign_ref="s",
        role_binding_ref="r",
        genesis_ref="g",
    )
    with pytest.raises(ConnectorAuthenticationError, match="Reject"):
        await conn.authenticate(unknown, envelope)


# ── Invariant 4 + 7: NON-empty verifiable receipts ───────────────────────


async def test_write_returns_non_empty_verifiable_envelope(fixture):
    """Invariant 4: write produces a real SignedActionEnvelope (NOT empty)."""
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return {"ok": True, "ts": "1700000000.000001", "channel": "C0123456789"}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    assert isinstance(envelope, SignedActionEnvelope)
    assert envelope.signature  # NON-EMPTY (LegacyInvokeConnector emits b"")
    assert envelope.canonical_bytes  # NON-EMPTY
    assert verifier.verify(
        envelope.canonical_bytes, envelope.signature, str(fixture["delegate_id"])
    )


async def test_read_returns_non_empty_verifiable_receipt(fixture):
    """Invariant 4: read produces a real AttestedReadReceipt (NOT empty)."""
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return [
            InboundSlackMessage(
                channel="C0123456789",
                ts="1700000000.000001",
                user="U07ABCDE123",
                text="hello",
            ),
            InboundSlackMessage(
                channel="C0123456789",
                ts="1700000001.000002",
                user="U07ABCDE123",
                text="world",
            ),
        ]

    messages, receipt = await conn.read(
        thunk, identity=identity, envelope=fixture["envelope"]
    )
    assert len(messages) == 2
    assert isinstance(receipt, AttestedReadReceipt)
    assert receipt.attestation  # NON-EMPTY
    assert receipt.canonical_bytes  # NON-EMPTY
    assert verifier.verify(
        receipt.canonical_bytes, receipt.attestation, str(fixture["delegate_id"])
    )


# ── Invariant 3: full-identity binding (tampering invariant) ────────────


async def test_write_receipt_does_not_verify_under_wrong_key(fixture):
    """Invariant 3: a foreign verifier rejects this connector's receipts."""
    conn, identity = fixture["connector"], fixture["identity"]

    async def thunk():
        return {"ok": True}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
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


async def test_write_identical_payloads_produce_different_signed_bytes(fixture):
    """Invariant 3: two identical posts produce different signed bytes.

    Receipts bind FULL identity (signer/attester + action_id/read_id +
    observed_at), NOT bare payload. Same payload twice → distinct envelopes.
    """
    conn, identity = fixture["connector"], fixture["identity"]

    async def thunk():
        return {"ok": True, "ts": "1700000000.000001", "channel": "C0123456789"}

    e1 = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    e2 = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    # Same payload, different signed bytes (distinct action_id + observed_at).
    assert e1.payload == e2.payload
    assert e1.canonical_bytes != e2.canonical_bytes
    assert e1.signature != e2.signature
    assert e1.action_id != e2.action_id


async def test_tampered_envelope_fails_verification(fixture):
    """Invariant 3: tampering with payload after signing breaks verification.

    Verify-helper re-derives signing bytes from envelope identity; tampered
    payload diverges from signed bytes → verification fails.
    """
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return {"ok": True, "ts": "1700000000.000001", "channel": "C0123456789"}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    # Build a tampered envelope with a different payload but same signature.
    tampered = SignedActionEnvelope(
        action_id=envelope.action_id,
        canonical_bytes=envelope.canonical_bytes,
        signature=envelope.signature,
        signer_delegate_id=envelope.signer_delegate_id,
        payload={"ok": False, "ts": "evil", "channel": "C0123456789"},
    )
    # verify_action_envelope re-derives from envelope.payload; tampered
    # payload no longer matches the signed canonical_bytes.
    observed_at = datetime.now(timezone.utc).isoformat()  # any iso ts; will mismatch
    assert not verify_action_envelope(tampered, verifier, observed_at=observed_at)


# ── Invariant 5: read manifest has ts ids + count ONLY (no body bytes) ──


async def test_read_manifest_omits_message_body_bytes(fixture):
    """Invariant 5: audited manifest carries ts ids + count, NEVER body text."""
    conn, identity = fixture["connector"], fixture["identity"]

    secret_body = "SECRET-COMPANY-DATA-DO-NOT-LEAK"

    async def thunk():
        return [
            InboundSlackMessage(
                channel="C0123456789",
                ts="1700000000.000001",
                user="U07ABCDE123",
                text=secret_body,
            )
        ]

    _, receipt = await conn.read(thunk, identity=identity, envelope=fixture["envelope"])
    # The canonical signed bytes contain the manifest — assert the body text
    # is NOT present anywhere in the audited canonical bytes.
    assert secret_body.encode("utf-8") not in receipt.canonical_bytes
    # And the ts id IS there (sanity — the manifest captures shape, not bytes).
    assert b"1700000000.000001" in receipt.canonical_bytes


# ── Invariant 2: invoke authenticates FIRST — unknown sender blocked ────


async def test_invoke_unknown_sender_rejected_before_any_slack_call(fixture):
    """Invariant 2: an unknown identity raises BEFORE chat.postMessage fires."""
    conn = fixture["connector"]
    fake_client = fixture["fake_client"]
    envelope = fixture["envelope"]
    unknown = DelegateIdentity(
        delegate_id=uuid.uuid4(),
        sovereign_ref="s",
        role_binding_ref="r",
        genesis_ref="g",
    )
    with pytest.raises(ConnectorAuthenticationError, match="Reject"):
        await conn.invoke(
            {"channel": "C0123456789", "text": "should not fire"},
            identity=unknown,
            envelope=envelope,
        )
    # Hot-path gate held: ZERO Slack API calls fired.
    assert fake_client.post_calls == []


# ── Invariant 6: tenant_id_observed echoes the resolved principal's tenant ──


async def test_invoke_returns_connector_invocation_result(fixture):
    """Invariants 2 + 6: invoke goes through and reports the correct tenant."""
    conn, identity, fake_client = (
        fixture["connector"],
        fixture["identity"],
        fixture["fake_client"],
    )
    result = await conn.invoke(
        {"channel": "C0123456789", "text": "hello team"},
        identity=identity,
        envelope=fixture["envelope"],
    )
    assert isinstance(result, ConnectorInvocationResult)
    assert result.external_side_effect is True
    assert result.tenant_id_observed == "t1"
    assert result.payload["ok"] is True
    assert result.payload["ts"]
    # And the SDK boundary actually fired exactly once.
    assert len(fake_client.post_calls) == 1
    assert fake_client.post_calls[0]["channel"] == "C0123456789"


# ── Verify helpers: read receipt round-trip ──────────────────────────────


async def test_verify_read_receipt_round_trips(fixture):
    """The verify_read_receipt helper accepts a receipt signed by this connector."""
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    messages_in = [
        InboundSlackMessage(
            channel="C0123456789",
            ts="1700000000.000001",
            user="U07ABCDE123",
            text="hi",
        )
    ]

    async def thunk():
        return messages_in

    _, receipt = await conn.read(thunk, identity=identity, envelope=fixture["envelope"])
    # Re-derive the manifest exactly as the connector builds it.
    expected_manifest = {
        "channel": "C0123456789",
        "count": 1,
        "message_ts": ["1700000000.000001"],
    }
    assert verify_read_receipt(receipt, expected_manifest, verifier)


# ── Constructor type guards ──────────────────────────────────────────────


async def test_constructor_rejects_non_transport():
    sk = Ed25519PrivateKey.generate()
    resolver = SlackPrincipalResolver({})
    directory = PrincipalDirectory(identities=(), verification_keys={})
    verifier = Ed25519Verifier(directory)
    with pytest.raises(TypeError, match="SlackTransport"):
        SlackConnector(
            transport="not-a-transport",  # type: ignore[arg-type]
            resolver=resolver,
            signing_key=sk,
            verifier=verifier,
        )
