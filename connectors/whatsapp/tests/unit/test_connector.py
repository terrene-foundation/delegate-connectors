# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for WhatsAppConnector.

The Connector / runtime CONTRACT is never mocked: the connector is the real
``kailash.delegate.dispatch.Connector`` subclass, receipts are signed with a
real Ed25519 key, and verified with the real shipped ``Ed25519Verifier``. The
only external boundary stubbed is the zero-arg async thunk passed to read/write
(the Cloud API side-effect), and the connector's own ``cloud_api.send`` on the
invoke hot path — driven via the connector's real transport, never a mock of
the connector itself.

Credentials (the PII HMAC key) come from ``monkeypatch.setenv``, never hardcoded.
The fixtures that construct a connector set ``WHATSAPP_PII_HMAC_KEY`` because the
``__init__`` startup gate (``RedactionConfig.from_env()``) refuses to construct
without it; the dedicated missing-key test deletes it to assert the refusal.
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

from delegate_connectors.whatsapp.cloud_api import (
    SendResult,
    WhatsAppCloudApi,
    WhatsAppCloudConfig,
)
from delegate_connectors.whatsapp.connector import (
    ConnectorAuthenticationError,
    WhatsAppConnector,
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors.whatsapp.directory import WhatsAppPrincipalResolver
from delegate_connectors.whatsapp.redaction import (
    PII_HMAC_KEY_ENV,
    RedactionConfigError,
)
from delegate_connectors.whatsapp.templates import (
    ServiceWindowTracker,
    TemplateGate,
)
from delegate_connectors.whatsapp.webhook import (
    InboundMessage,
    WebhookConfig,
    WebhookIngest,
)

pytestmark = pytest.mark.asyncio

_SENDER_PHONE = "14155550100"


def _cloud_api() -> WhatsAppCloudApi:
    return WhatsAppCloudApi(
        WhatsAppCloudConfig(
            access_token="tok", phone_number_id="1", graph_version="18.0"
        )
    )


def _ingest(window_tracker: ServiceWindowTracker) -> WebhookIngest:
    return WebhookIngest(
        WebhookConfig(app_secret="sek", verify_token="vt"),
        window_sink=window_tracker.record_inbound,
    )


@pytest.fixture
def fixture(monkeypatch):
    # Startup gate: the connector's __init__ calls RedactionConfig.from_env().
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-pii-hmac-key-min-len")

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
    principal = Principal(
        delegate_id=str(delegate_id),
        tenant_id="t1",
        claims={"phone": _SENDER_PHONE},
    )
    resolver = WhatsAppPrincipalResolver({_SENDER_PHONE: principal})

    window_tracker = ServiceWindowTracker()
    # Open the sender's 24h window so free-form invoke is allowed.
    window_tracker.record_inbound(_SENDER_PHONE)
    template_gate = TemplateGate({"order_update"}, window_tracker)

    connector = WhatsAppConnector(
        cloud_api=_cloud_api(),
        ingest=_ingest(window_tracker),
        resolver=resolver,
        template_gate=template_gate,
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
        block=genesis_block, spec_version="0", capabilities=("whatsapp.send",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)
    return {
        "connector": connector,
        "identity": identity,
        "verifier": verifier,
        "envelope": envelope,
        "delegate_id": delegate_id,
    }


# ── ABC compliance + trust properties ────────────────────────────────────


async def test_connector_satisfies_abc(fixture):
    conn = fixture["connector"]
    assert isinstance(conn, Connector)
    assert WhatsAppConnector.__abstractmethods__ == frozenset()


async def test_trust_properties_return_concretes_never_raise(fixture):
    conn = fixture["connector"]
    assert isinstance(conn.auth_verifier, Ed25519Verifier)
    # ledger + revocation must not raise on access (the LegacyInvokeConnector
    # failure mode this connector exists to avoid).
    assert conn.ledger is not None
    assert conn.revocation.is_revoked("anyone") is False


# ── Startup gate — missing PII HMAC key refuses construction ─────────────


async def test_init_raises_when_pii_hmac_key_unset(monkeypatch):
    monkeypatch.delenv(PII_HMAC_KEY_ENV, raising=False)
    sk = Ed25519PrivateKey.generate()
    delegate_id = uuid.uuid4()
    identity = DelegateIdentity(
        delegate_id=delegate_id,
        sovereign_ref="s",
        role_binding_ref="r",
        genesis_ref="g",
    )
    directory = PrincipalDirectory(
        identities=(identity,),
        verification_keys={delegate_id: sk.public_key().public_bytes_raw()},
    )
    verifier = Ed25519Verifier(directory)
    window_tracker = ServiceWindowTracker()
    with pytest.raises(RedactionConfigError, match=PII_HMAC_KEY_ENV):
        WhatsAppConnector(
            cloud_api=_cloud_api(),
            ingest=_ingest(window_tracker),
            resolver=WhatsAppPrincipalResolver({}),
            template_gate=TemplateGate(set(), window_tracker),
            signing_key=sk,
            verifier=verifier,
        )


# ── authenticate — fail-closed on unknown identity ───────────────────────


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


# ── write — non-empty, verifiable, identity-bound envelope ───────────────


async def test_write_returns_non_empty_verifiable_envelope(fixture):
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return {"wamid": "wamid.X", "wa_id": _SENDER_PHONE, "to": _SENDER_PHONE}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    assert isinstance(envelope, SignedActionEnvelope)
    assert envelope.signature  # NON-EMPTY (LegacyInvokeConnector emits b"")
    assert envelope.canonical_bytes
    # verify_action_envelope re-derives identity-bound bytes AND checks the sig.
    assert verify_action_envelope(
        envelope, verifier, observed_at=_observed_at(envelope)
    )


async def test_write_redacts_recipient_pii_in_signed_payload(fixture):
    """The raw wa_id / to MUST NOT appear in the signed canonical bytes."""
    conn, identity = fixture["connector"], fixture["identity"]

    async def thunk():
        return {"wamid": "wamid.X", "wa_id": _SENDER_PHONE, "to": _SENDER_PHONE}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    # Raw number never lands in the signed bytes or the payload.
    assert _SENDER_PHONE not in envelope.canonical_bytes.decode("utf-8")
    assert envelope.payload["wa_id"].startswith("wa:")
    assert envelope.payload["to"].startswith("wa:")


async def test_write_receipt_does_not_verify_under_wrong_key(fixture):
    conn, identity = fixture["connector"], fixture["identity"]

    async def thunk():
        return {"sent": True}

    envelope = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    foreign_sk = Ed25519PrivateKey.generate()
    foreign_dir = PrincipalDirectory(
        identities=(fixture["identity"],),
        verification_keys={
            fixture["delegate_id"]: foreign_sk.public_key().public_bytes_raw()
        },
    )
    foreign_verifier = Ed25519Verifier(foreign_dir)
    assert not verify_action_envelope(
        envelope, foreign_verifier, observed_at=_observed_at(envelope)
    )


# ── read — non-empty, verifiable attestation; bodies/senders omitted ─────


async def test_read_returns_non_empty_verifiable_receipt(fixture):
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return [
            InboundMessage(
                sender_redacted="wa:deadbeef",
                message_type="text",
                text="hello",
                timestamp="1700000000",
                message_id="wamid.M1",
            )
        ]

    messages, receipt = await conn.read(
        thunk, identity=identity, envelope=fixture["envelope"]
    )
    assert len(messages) == 1
    assert isinstance(receipt, AttestedReadReceipt)
    assert receipt.attestation  # NON-EMPTY
    assert receipt.canonical_bytes
    manifest = {"count": 1, "message_ids": ["wamid.M1"]}
    assert verify_read_receipt(receipt, manifest, verifier)
    # Bodies / senders never enter the signed manifest — only ids + count.
    assert "hello" not in receipt.canonical_bytes.decode("utf-8")
    assert "wa:deadbeef" not in receipt.canonical_bytes.decode("utf-8")


# ── invoke — fail-closed auth ordering + side-effect result ──────────────


async def test_invoke_returns_connector_invocation_result(fixture, monkeypatch):
    conn, identity = fixture["connector"], fixture["identity"]

    async def fake_send(message):
        return SendResult(wamid="wamid.INV", wa_id=message.to)

    # Stub the connector's OWN transport send (the external Cloud API boundary),
    # not the connector contract.
    monkeypatch.setattr(conn._cloud_api, "send", fake_send)
    result = await conn.invoke(
        {"to": _SENDER_PHONE, "text": "yo"},
        identity=identity,
        envelope=fixture["envelope"],
    )
    assert isinstance(result, ConnectorInvocationResult)
    assert result.external_side_effect is True
    assert result.tenant_id_observed == "t1"
    # Recipient PII redacted in the result payload.
    assert result.payload["wamid"] == "wamid.INV"
    assert result.payload["to"].startswith("wa:")


async def test_invoke_unknown_sender_rejects_before_any_send(fixture, monkeypatch):
    """The unknown-sender Reject fires BEFORE any Cloud API send is attempted."""
    conn, envelope = fixture["connector"], fixture["envelope"]
    send_calls: list = []

    async def fake_send(message):
        send_calls.append(message)
        return SendResult(wamid="wamid.X", wa_id=message.to)

    monkeypatch.setattr(conn._cloud_api, "send", fake_send)
    unknown = DelegateIdentity(
        delegate_id=uuid.uuid4(),
        sovereign_ref="s",
        role_binding_ref="r",
        genesis_ref="g",
    )
    with pytest.raises(ConnectorAuthenticationError, match="Reject"):
        await conn.invoke(
            {"to": _SENDER_PHONE, "text": "yo"}, identity=unknown, envelope=envelope
        )
    # Fail-closed: no send fired on the unknown-sender path.
    assert send_calls == []


# ── helper ────────────────────────────────────────────────────────────────


def _observed_at(envelope: SignedActionEnvelope) -> str:
    """Recover the observed_at that produced the envelope's signed bytes.

    ``write`` binds ``observed_at`` into the canonical bytes but does not expose
    it on the envelope; we re-derive it by searching the canonical JSON. Because
    the test owns the payload + identity, the only unknown is observed_at — which
    is embedded verbatim in the canonical JSON, so we parse it back out.
    """
    import json

    decoded = json.loads(envelope.canonical_bytes.decode("utf-8"))
    return decoded["observed_at"]
