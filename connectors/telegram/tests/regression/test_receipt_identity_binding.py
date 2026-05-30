# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression: receipt identity binding (T-ADR-3, the receipt-forgery defense).

These tests lock the invariant that every receipt binds its full identity —
signer/action-id/observed-at for writes, attester/read-id/observed-at for
reads — so two identical-payload operations produce DIFFERENT signed bytes and
any tampering with a bound field fails verification.

Behavioral (NOT source-grep) per ``rules/testing.md``: each test calls the real
``write`` / ``read`` primitive and asserts on the returned receipt + verifier
outcome. If the binding regresses (e.g. someone reverts to signing the bare
payload), the determinism + tamper assertions fail.
"""

from __future__ import annotations

import pytest

from delegate_connectors.telegram.connector import (
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors.telegram.transport import InboundUpdate

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


async def test_identical_payload_writes_produce_distinct_envelopes(
    telegram_regression_composed,
):
    """Two writes with identical payloads → DIFFERENT action_id + signed bytes."""
    composed = telegram_regression_composed

    async def thunk():
        return {"message_id": 99, "chat_id": 555000, "ok": True}

    e1 = await composed.connector.write(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    e2 = await composed.connector.write(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    assert e1.action_id != e2.action_id
    assert e1.canonical_bytes != e2.canonical_bytes
    assert e1.signature != e2.signature
    # Both still verify under the composed verifier (bound identity).
    assert composed.verifier.verify(
        e1.canonical_bytes, e1.signature, str(composed.identity.delegate_id)
    )
    assert composed.verifier.verify(
        e2.canonical_bytes, e2.signature, str(composed.identity.delegate_id)
    )


async def test_write_envelope_verifies_with_bound_identity(
    telegram_regression_composed,
):
    """A freshly signed write envelope verifies under the bound signer identity."""
    composed = telegram_regression_composed

    async def thunk():
        return {"message_id": 7, "chat_id": 555000, "ok": True}

    envelope = await composed.connector.write(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    assert envelope.signer_delegate_id == str(composed.identity.delegate_id)
    assert composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )


async def test_tampered_signer_fails_verification(telegram_regression_composed):
    """Flipping the signer id after signing fails verification (identity bound)."""
    composed = telegram_regression_composed

    async def thunk():
        return {"message_id": 5, "chat_id": 555000, "ok": True}

    envelope = await composed.connector.write(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    # Tamper: rebind the signer id on a copy and verify it fails.
    tampered = envelope.__class__(
        action_id=envelope.action_id,
        canonical_bytes=envelope.canonical_bytes,
        signature=envelope.signature,
        signer_delegate_id="attacker-delegate-id",
        payload=envelope.payload,
    )
    assert verify_action_envelope(tampered, composed.verifier, observed_at="") is False
    assert not composed.verifier.verify(
        tampered.canonical_bytes, tampered.signature, "attacker-delegate-id"
    )


async def test_read_receipt_binds_attester(telegram_regression_composed):
    """A read receipt binds the attester; the re-derived manifest verifies."""
    composed = telegram_regression_composed

    async def thunk():
        return [
            InboundUpdate(
                update_id=1, message_id=2, chat_id=555000, from_user_id=7, text="hi"
            )
        ]

    _value, receipt = await composed.connector.read(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    assert receipt.attester_delegate_id == str(composed.identity.delegate_id)
    manifest = {"count": 1, "update_ids": [1], "message_ids": [2]}
    assert verify_read_receipt(receipt, manifest, composed.verifier) is True


async def test_tampered_read_attester_fails_verification(
    telegram_regression_composed,
):
    """Flipping the attester id after signing fails read-receipt verification."""
    composed = telegram_regression_composed

    async def thunk():
        return [
            InboundUpdate(
                update_id=1, message_id=2, chat_id=555000, from_user_id=7, text="hi"
            )
        ]

    _value, receipt = await composed.connector.read(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    tampered = receipt.__class__(
        read_id=receipt.read_id,
        canonical_bytes=receipt.canonical_bytes,
        attestation=receipt.attestation,
        attester_delegate_id="attacker-delegate-id",
        observed_at=receipt.observed_at,
    )
    manifest = {"count": 1, "update_ids": [1], "message_ids": [2]}
    assert verify_read_receipt(tampered, manifest, composed.verifier) is False
