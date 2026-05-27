# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — L2 (LOW): receipt identity not bound into signed bytes.

Before this fix, `write` signed only `canonical_json_dumps(payload)` and `read`
signed only `canonical_json_dumps(manifest)`. Two receipts with identical
payloads were byte-identical, and `signer_delegate_id`/`action_id`/`observed_at`
were unbound — a replay/forge surface.

Fix: `write` signs over `{payload, signer_delegate_id, action_id, observed_at}`
and `read` over `{manifest, attester_delegate_id, read_id, observed_at}`. The
`verify_action_envelope` / `verify_read_receipt` helpers re-derive the signing
bytes from the receipt's own identity fields, so tampering with any bound field
fails verification.
"""

from __future__ import annotations

import dataclasses
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
    EmailConnector,
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors.email.directory import EmailPrincipalResolver
from delegate_connectors.email.imap import (
    ImapConfig,
    ImapTransport,
    InboundMessage,
)
from delegate_connectors.email.smtp import SmtpConfig, SmtpTransport

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


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


async def test_two_same_payload_writes_have_different_signatures(fixture):
    """Identical payloads no longer produce byte-identical / replayable receipts."""
    conn, identity, envelope = (
        fixture["connector"],
        fixture["identity"],
        fixture["envelope"],
    )

    async def thunk():
        return {"message_id": "<m@x>", "accepted": True, "recipient": "bob@x.com"}

    e1 = await conn.write(thunk, identity=identity, envelope=envelope)
    e2 = await conn.write(thunk, identity=identity, envelope=envelope)

    # Same payload, but distinct action_id (+ observed_at) bound into the signed
    # bytes -> different canonical bytes -> different signatures.
    assert e1.payload == e2.payload
    assert e1.action_id != e2.action_id
    assert e1.canonical_bytes != e2.canonical_bytes
    assert e1.signature != e2.signature


async def test_action_envelope_verifies_with_bound_identity(fixture):
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    # observed_at lives inside the signed canonical bytes; re-derive via the
    # helper and confirm the bound-identity verification passes.
    import json

    observed_at = json.loads(env.canonical_bytes.decode("utf-8"))["observed_at"]
    assert verify_action_envelope(env, verifier, observed_at=observed_at) is True


async def test_tampered_signer_delegate_id_fails_verification(fixture):
    """A receipt whose signer_delegate_id is swapped fails identity-bound verify."""
    conn, identity, verifier = (
        fixture["connector"],
        fixture["identity"],
        fixture["verifier"],
    )

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=fixture["envelope"])
    import json

    observed_at = json.loads(env.canonical_bytes.decode("utf-8"))["observed_at"]

    # Tamper: replace signer_delegate_id while keeping the signed canonical_bytes.
    tampered = dataclasses.replace(env, signer_delegate_id="attacker-delegate-id")
    # The re-derived bytes from the tampered field diverge from the signed bytes
    # -> verification fails.
    assert verify_action_envelope(tampered, verifier, observed_at=observed_at) is False


async def test_read_receipt_binds_attester_and_verifies(fixture):
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
    manifest = {"count": 1, "message_ids": ["<m1@x>"]}
    assert verify_read_receipt(receipt, manifest, verifier) is True

    # Tamper the attester id -> bound verification fails.
    tampered = dataclasses.replace(receipt, attester_delegate_id="attacker")
    assert verify_read_receipt(tampered, manifest, verifier) is False
