# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — binding security property 4: receipt identity-binding tamper.

``write`` signs over ``{payload, signer_delegate_id, action_id, observed_at}``
and ``read`` over ``{manifest, attester_delegate_id, read_id, observed_at}``.
``verify_action_envelope`` / ``verify_read_receipt`` re-derive the signing bytes
from the receipt's OWN identity fields, so tampering with ANY bound field makes
the re-derived bytes diverge from the signed bytes — verification fails.

Invariant 4: tampering ANY bound field fails verification (one assertion per
mutated field — signer / action_id / observed_at on the write envelope;
attester / read_id / observed_at on the read receipt).
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest

from delegate_connectors.whatsapp.connector import (
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors.whatsapp.webhook import InboundMessage

from .conftest import SENDER_PHONE

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


def _observed_at(envelope) -> str:
    """Recover the observed_at bound into a write envelope's signed bytes."""
    return json.loads(envelope.canonical_bytes.decode("utf-8"))["observed_at"]


# ── write envelope — three bound fields ──────────────────────────────────


async def test_action_envelope_verifies_unmodified(wa):
    """Baseline: an untampered write envelope verifies under the real verifier."""
    conn, identity, verifier = wa["connector"], wa["identity"], wa["verifier"]

    async def thunk():
        return {"wamid": "wamid.X", "wa_id": SENDER_PHONE, "to": SENDER_PHONE}

    env = await conn.write(thunk, identity=identity, envelope=wa["envelope"])
    assert verify_action_envelope(env, verifier, observed_at=_observed_at(env)) is True


async def test_tampered_signer_delegate_id_fails(wa):
    """Mutate signer_delegate_id → bound verification fails."""
    conn, identity, verifier = wa["connector"], wa["identity"], wa["verifier"]

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=wa["envelope"])
    tampered = dataclasses.replace(env, signer_delegate_id="attacker-delegate-id")
    assert (
        verify_action_envelope(tampered, verifier, observed_at=_observed_at(env))
        is False
    )


async def test_tampered_action_id_fails(wa):
    """Mutate action_id → re-derived bytes diverge → verification fails."""
    conn, identity, verifier = wa["connector"], wa["identity"], wa["verifier"]

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=wa["envelope"])
    tampered = dataclasses.replace(env, action_id=uuid.uuid4())
    assert (
        verify_action_envelope(tampered, verifier, observed_at=_observed_at(env))
        is False
    )


async def test_tampered_observed_at_fails(wa):
    """Pass a DIFFERENT observed_at than the one signed → verification fails."""
    conn, identity, verifier = wa["connector"], wa["identity"], wa["verifier"]

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=wa["envelope"])
    # observed_at is bound into the signed bytes; supplying a different value to
    # the verifier re-derives divergent bytes -> fails.
    assert (
        verify_action_envelope(env, verifier, observed_at="1999-01-01T00:00:00+00:00")
        is False
    )


async def test_tampered_payload_fails(wa):
    """Mutate the payload → re-derived bytes diverge → verification fails."""
    conn, identity, verifier = wa["connector"], wa["identity"], wa["verifier"]

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=wa["envelope"])
    tampered = dataclasses.replace(env, payload={"sent": False})
    assert (
        verify_action_envelope(tampered, verifier, observed_at=_observed_at(env))
        is False
    )


# ── read receipt — three bound fields ────────────────────────────────────


async def _signed_receipt(wa):
    conn, identity = wa["connector"], wa["identity"]

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

    _messages, receipt = await conn.read(
        thunk, identity=identity, envelope=wa["envelope"]
    )
    manifest = {"count": 1, "message_ids": ["wamid.M1"]}
    return receipt, manifest


async def test_read_receipt_verifies_unmodified(wa):
    """Baseline: an untampered read receipt verifies under the real verifier."""
    receipt, manifest = await _signed_receipt(wa)
    assert verify_read_receipt(receipt, manifest, wa["verifier"]) is True


async def test_tampered_attester_delegate_id_fails(wa):
    """Mutate attester_delegate_id → bound verification fails."""
    receipt, manifest = await _signed_receipt(wa)
    tampered = dataclasses.replace(receipt, attester_delegate_id="attacker")
    assert verify_read_receipt(tampered, manifest, wa["verifier"]) is False


async def test_tampered_read_id_fails(wa):
    """Mutate read_id → re-derived bytes diverge → verification fails."""
    receipt, manifest = await _signed_receipt(wa)
    tampered = dataclasses.replace(receipt, read_id=uuid.uuid4())
    assert verify_read_receipt(tampered, manifest, wa["verifier"]) is False


async def test_tampered_observed_at_on_receipt_fails(wa):
    """Mutate observed_at → re-derived bytes diverge → verification fails."""
    from datetime import datetime, timezone

    receipt, manifest = await _signed_receipt(wa)
    tampered = dataclasses.replace(
        receipt, observed_at=datetime(1999, 1, 1, tzinfo=timezone.utc)
    )
    assert verify_read_receipt(tampered, manifest, wa["verifier"]) is False


async def test_tampered_manifest_fails(wa):
    """Mutate the manifest the verifier re-derives over → verification fails."""
    receipt, _manifest = await _signed_receipt(wa)
    forged_manifest = {"count": 99, "message_ids": ["wamid.FORGED"]}
    assert verify_read_receipt(receipt, forged_manifest, wa["verifier"]) is False
