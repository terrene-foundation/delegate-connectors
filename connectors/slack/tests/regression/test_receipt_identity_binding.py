# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — receipts bind FULL identity into the signed bytes.

``write`` signs over ``{payload, signer_delegate_id, action_id, observed_at}`` and
``read`` over ``{manifest, attester_delegate_id, read_id, observed_at}``.
``verify_action_envelope`` / ``verify_read_receipt`` re-derive the signing bytes
from the receipt's OWN identity fields, so tampering with ANY bound field makes the
re-derived bytes diverge from the signed bytes — verification fails.

Behavioral: call the real ``write`` / ``read`` then assert the verify helper's
return value. NEVER source-grep.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest

from delegate_connectors.slack.connector import (
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors.slack.messages import InboundSlackMessage

from .conftest import CHANNEL_ID

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


def _observed_at(envelope) -> str:
    """Recover the observed_at bound into a write envelope's signed bytes."""
    return json.loads(envelope.canonical_bytes.decode("utf-8"))["observed_at"]


# ── identical payloads → distinct signed bytes / signatures / action ids ───


async def test_identical_payloads_produce_distinct_signed_receipts(slack):
    """Two identical-payload writes have distinct action_id/bytes/signatures."""
    conn, identity = slack["connector"], slack["identity"]

    async def thunk():
        return {"ok": True, "ts": "1700000000.000001", "channel": CHANNEL_ID}

    e1 = await conn.write(thunk, identity=identity, envelope=slack["envelope"])
    e2 = await conn.write(thunk, identity=identity, envelope=slack["envelope"])

    assert e1.payload == e2.payload
    assert e1.action_id != e2.action_id
    assert e1.canonical_bytes != e2.canonical_bytes
    assert e1.signature != e2.signature


# ── write envelope — baseline + bound-field tamper fails ───────────────────


async def test_action_envelope_verifies_unmodified(slack):
    """Baseline: an untampered write envelope verifies under the real verifier."""
    conn, identity, verifier = slack["connector"], slack["identity"], slack["verifier"]

    async def thunk():
        return {"ok": True, "ts": "1700000000.000001", "channel": CHANNEL_ID}

    env = await conn.write(thunk, identity=identity, envelope=slack["envelope"])
    assert verify_action_envelope(env, verifier, observed_at=_observed_at(env)) is True


async def test_tampered_signer_delegate_id_fails(slack):
    """Mutate signer_delegate_id → bound verification fails."""
    conn, identity, verifier = slack["connector"], slack["identity"], slack["verifier"]

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=slack["envelope"])
    tampered = dataclasses.replace(env, signer_delegate_id="attacker-delegate-id")
    assert (
        verify_action_envelope(tampered, verifier, observed_at=_observed_at(env))
        is False
    )


async def test_tampered_action_id_fails(slack):
    """Mutate action_id → re-derived bytes diverge → verification fails."""
    conn, identity, verifier = slack["connector"], slack["identity"], slack["verifier"]

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=slack["envelope"])
    tampered = dataclasses.replace(env, action_id=uuid.uuid4())
    assert (
        verify_action_envelope(tampered, verifier, observed_at=_observed_at(env))
        is False
    )


async def test_tampered_payload_fails(slack):
    """Mutate the payload → re-derived bytes diverge → verification fails."""
    conn, identity, verifier = slack["connector"], slack["identity"], slack["verifier"]

    async def thunk():
        return {"sent": True}

    env = await conn.write(thunk, identity=identity, envelope=slack["envelope"])
    tampered = dataclasses.replace(env, payload={"sent": False})
    assert (
        verify_action_envelope(tampered, verifier, observed_at=_observed_at(env))
        is False
    )


# ── read receipt — baseline + bound-field tamper fails ─────────────────────


async def _signed_receipt(slack):
    conn, identity = slack["connector"], slack["identity"]

    async def thunk():
        return [
            InboundSlackMessage(
                channel=CHANNEL_ID,
                ts="1700000000.000001",
                user="U07ABCDE123",
                text="hello",
            )
        ]

    _messages, receipt = await conn.read(
        thunk, identity=identity, envelope=slack["envelope"]
    )
    manifest = {
        "channel": CHANNEL_ID,
        "count": 1,
        "message_ts": ["1700000000.000001"],
    }
    return receipt, manifest


async def test_read_receipt_verifies_unmodified(slack):
    """Baseline: an untampered read receipt verifies under the real verifier."""
    receipt, manifest = await _signed_receipt(slack)
    assert verify_read_receipt(receipt, manifest, slack["verifier"]) is True


async def test_tampered_attester_delegate_id_fails(slack):
    """Mutate attester_delegate_id → bound verification fails."""
    receipt, manifest = await _signed_receipt(slack)
    tampered = dataclasses.replace(receipt, attester_delegate_id="attacker")
    assert verify_read_receipt(tampered, manifest, slack["verifier"]) is False


async def test_tampered_read_id_fails(slack):
    """Mutate read_id → re-derived bytes diverge → verification fails."""
    receipt, manifest = await _signed_receipt(slack)
    tampered = dataclasses.replace(receipt, read_id=uuid.uuid4())
    assert verify_read_receipt(tampered, manifest, slack["verifier"]) is False


async def test_tampered_manifest_fails(slack):
    """Mutate the manifest the verifier re-derives over → verification fails."""
    receipt, _manifest = await _signed_receipt(slack)
    forged_manifest = {
        "channel": CHANNEL_ID,
        "count": 99,
        "message_ts": ["9999999999.000000"],
    }
    assert verify_read_receipt(receipt, forged_manifest, slack["verifier"]) is False
