# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-2 integration: real connector round-trips against the Bot API double.

NO mocks at the boundary. The REAL
:class:`~delegate_connectors.telegram.transport.TelegramTransport` runs over a
REAL :class:`httpx.AsyncClient` whose byte stream terminates at the in-process
protocol-faithful Bot API double (T-ADR-1). Real Ed25519 key + the shipped
:class:`~kailash.delegate.verifier.Ed25519Verifier` from the composed runtime.

Two round-trips:

- **Send**: drive the connector ``write`` path with a thunk that POSTs through
  the real transport. Assert (a) the request the double received matches the
  Bot API ``sendMessage`` contract (URL suffix, JSON body), (b) the message
  transits the double (assert via the double's delivered/getUpdates surface,
  NOT connector internal state), and (c) the signed envelope verifies under the
  composed real verifier.
- **Inbound**: long-poll ``getUpdates`` through the connector ``read`` path →
  assert a verifiable, identity-bound :class:`AttestedReadReceipt`. Tamper a
  bound field → verification fails.
"""

from __future__ import annotations

import pytest

from delegate_connectors.telegram.connector import verify_read_receipt
from delegate_connectors.telegram.transport import OutboundMessage

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_RECIPIENT_CHAT_ID = 555000


async def test_send_path_matches_botapi_contract_and_transits_double(
    telegram_composed, botapi_double
):
    """The audited write path POSTs the Bot API sendMessage shape; msg transits."""
    composed = telegram_composed
    transport = composed.connector._transport

    captured: dict[str, object] = {}

    async def send_thunk():
        result = await transport.send(
            OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text="hello over the double")
        )
        captured["result"] = result
        return {
            "message_id": result.message_id,
            "chat_id": result.chat_id,
            "ok": result.ok,
        }

    # Audited write — the Bot API POST is the external side effect.
    envelope = await composed.connector.write(
        send_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    # 1. The request the double received matches the Bot API sendMessage contract.
    #    The URL embeds the bot token in the path; assert only the method
    #    segment so neither the token nor the full URL is asserted/logged.
    req = botapi_double.last_request
    assert req.method == "POST"
    assert req.method_name == "sendMessage"
    assert req.url.endswith("/sendMessage")
    assert req.json_body["chat_id"] == _RECIPIENT_CHAT_ID
    assert req.json_body["text"] == "hello over the double"

    # 2. The message transited the double — assert via the double's surface, not
    #    connector internal state.
    assert botapi_double.delivered, "the double recorded zero delivered sends"
    assert botapi_double.delivered[-1]["chat_id"] == _RECIPIENT_CHAT_ID
    assert botapi_double.delivered[-1]["text"] == "hello over the double"

    # 3. The SendResult carries the deterministic message_id the double reported.
    send_result = captured["result"]
    assert send_result.message_id == botapi_double.delivered[-1]["message_id"]
    assert send_result.ok is True

    # 4. The signed envelope is non-empty, carries the message_id, and verifies
    #    under the composed REAL Ed25519Verifier.
    #    Direct-verify idiom (mirrors whatsapp's own roundtrip test): the
    #    `observed_at` bound into the signed canonical_bytes is NOT echoed in
    #    `envelope.payload`, so the `verify_action_envelope` helper (which
    #    re-derives bytes from payload + observed_at) returns False here and
    #    cannot be driven without the timestamp — that helper is covered by the
    #    Tier-1 unit suite where the observed_at boundary is recorded. Here we
    #    verify the signature directly over the actual signed bytes, NO masking `or`.
    assert envelope.signature and envelope.canonical_bytes
    assert envelope.payload["message_id"] == send_result.message_id
    assert composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )


async def test_two_identical_sends_yield_identical_message_id(
    telegram_composed, botapi_double
):
    """Determinism at the transport boundary: identical send bodies → same message_id."""
    composed = telegram_composed
    transport = composed.connector._transport

    r1 = await transport.send(
        OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text="determinism probe")
    )
    r2 = await transport.send(
        OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text="determinism probe")
    )
    assert r1.message_id == r2.message_id


async def test_inbound_getupdates_round_trips_through_read(
    telegram_composed, botapi_double
):
    """getUpdates long-poll → connector read → verifiable AttestedReadReceipt."""
    composed = telegram_composed
    transport = composed.connector._transport

    # Prime the double with one delivered send so getUpdates has an update to
    # replay (the double replays recorded sends as Updates).
    await transport.send(OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text="inbound hi"))

    async def drain_thunk():
        return await transport.get_updates(timeout=0)

    updates, receipt = await composed.connector.read(
        drain_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    assert len(updates) == 1
    assert updates[0].text == "inbound hi"
    assert updates[0].chat_id == _RECIPIENT_CHAT_ID

    # The attestation is non-empty and the full identity-bound receipt verifies:
    # the manifest re-derived from the drained updates matches the signed bytes.
    assert receipt.attestation and receipt.canonical_bytes
    assert composed.verifier.verify(
        receipt.canonical_bytes,
        receipt.attestation,
        str(composed.identity.delegate_id),
    )
    manifest = {
        "count": len(updates),
        "update_ids": [u.update_id for u in updates],
        "message_ids": [u.message_id for u in updates],
    }
    assert verify_read_receipt(receipt, manifest, composed.verifier) is True


async def test_inbound_receipt_tamper_fails_verification(
    telegram_composed, botapi_double
):
    """Tampering a bound field on the read receipt fails verification (identity bound)."""
    composed = telegram_composed
    transport = composed.connector._transport
    await transport.send(OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text="bind me"))

    async def drain_thunk():
        return await transport.get_updates(timeout=0)

    updates, receipt = await composed.connector.read(
        drain_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    # Tamper: rebind the attester id on a copy and verify it fails.
    tampered = receipt.__class__(
        read_id=receipt.read_id,
        canonical_bytes=receipt.canonical_bytes,
        attestation=receipt.attestation,
        attester_delegate_id="attacker-delegate-id",
        observed_at=receipt.observed_at,
    )
    manifest = {
        "count": len(updates),
        "update_ids": [u.update_id for u in updates],
        "message_ids": [u.message_id for u in updates],
    }
    assert verify_read_receipt(tampered, manifest, composed.verifier) is False
