# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-3 e2e: compose a DelegateRuntime and drive it against the Bot API double.

The end-to-end ``runtime.execute()`` OUTCOME assertion (a COMPLETED run carrying
a verifiable SignedActionEnvelope) is GATED on an SDK fix: the shipped
``kailash.delegate`` runtime audit-emit path signs the event PAYLOAD bytes while
``AuditChainEngine.emit_event`` verifies the FULL audit-entry signing bytes, so
``execute()`` fails at the first phase transition under ANY real verifier
(kailash-py#1182, compose.py module docstring "KNOWN SDK BLOCKER"). The outcome
assertion is a STRICT xfail — when the SDK ships the fix it flips to XPASS and
forces the marker's removal.

Intra-impl receipt determinism is asserted SEPARATELY via
``assert_receipts_agree``: it holds regardless of the phase outcome, which is
exactly the cross-impl-agreement contract the spec asks v0 to demonstrate.

This is Tier-2 against the in-process protocol-faithful Bot API double (T-ADR-1).
The opt-in Tier-3 live Telegram test lives below behind the
``requires_live_telegram`` gate — it SKIPS with a "cannot execute" reason when
no live ``TELEGRAM_*`` creds are present, never a mock.
"""

from __future__ import annotations

import pytest

from kailash.delegate import assert_receipts_agree

from delegate_connectors.telegram.transport import OutboundMessage

from _botapi_double import BotApiDouble
from _live_telegram import requires_live_telegram
from _telegram_compose import compose_fresh

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_RECIPIENT_CHAT_ID = 555000


def _send_payload() -> dict[str, object]:
    return {"chat_id": _RECIPIENT_CHAT_ID, "text": "e2e hello"}


async def test_runtime_execute_e2e_against_double_completes(telegram_composed):
    """End-to-end run completes against the socket double on kailash >= 2.28.0.

    Was strict-xfailed on kailash-py#1182 (audit-emit signed payload bytes while
    AuditChainEngine verified full entry bytes; execute() failed at the first
    phase transition). Fixed at <= 2.28.1 (workspaces/whatsapp/journal/0008); the
    marker is removed and the run now completes carrying a dispatch result.
    """
    composed = telegram_composed
    result = await composed.runtime.execute(_send_payload())
    assert result.taod_state.phase == "completed"
    assert result.dispatch_result is not None


async def test_runtime_execute_is_deterministic_across_two_runs():
    """Two fresh runtimes given identical input produce agreeing receipts.

    ``assert_receipts_agree`` deep-compares the receipt tree minus the per-run
    identity fields: ``run_id`` + the per-transition ``at`` timestamp, plus the
    three fields that are per-run-by-design now that execute() completes —
    ``dispatch_id`` (a fresh UUID per dispatch), ``audit_head_hash`` and
    ``audit_chain_entries`` (SHA-256 hashes that incorporate ``dispatch_id`` and
    per-run audit state). Audit-chain *integrity* (round-trip + head-hash
    re-validation) is a distinct property covered by the conformance vector
    DV-9-001; this test asserts the *outcome* is deterministic (same phase,
    transition shape, dispatch result) for identical input.
    """
    payload = _send_payload()
    double_a = BotApiDouble()
    double_b = BotApiDouble()
    composed_a, client_a = compose_fresh(double_a)
    composed_b, client_b = compose_fresh(double_b)
    try:
        r1 = await composed_a.runtime.execute(dict(payload))
        r2 = await composed_b.runtime.execute(dict(payload))
        assert_receipts_agree(
            r1.to_dict(),
            r2.to_dict(),
            exclude_fields=frozenset(
                {
                    "run_id",
                    "at",
                    "dispatch_id",
                    "audit_head_hash",
                    "audit_chain_entries",
                }
            ),
        )
    finally:
        await client_a.aclose()
        await client_b.aclose()


@requires_live_telegram
async def test_live_telegram():
    """Tier-3 LIVE: send a real message via the live Telegram Bot API.

    Opt-in only — SKIPS with a "cannot execute" reason when no live
    ``TELEGRAM_*`` creds are present. NEVER a mock fallback: absent creds, the
    test does not run. When it runs, it builds the REAL transport from env (no
    injected client → a live httpx client against api.telegram.org) and asserts
    a real message_id comes back through an audited, verifying envelope.
    """
    import os

    from delegate_connectors.telegram.compose import build_telegram_runtime
    from delegate_connectors.telegram.transport import TelegramTransport

    chat_id = int(os.environ["TELEGRAM_LIVE_E2E_CHAT_ID"])
    user_id = int(os.environ.get("TELEGRAM_LIVE_E2E_USER_ID", str(chat_id)))

    # Real transport: no injected client, so each send opens a short-lived
    # httpx client against the live Telegram Bot API.
    transport = TelegramTransport.from_env()
    composed = build_telegram_runtime(
        transport=transport,
        sender_user_id=user_id,
        sender_chat_id=chat_id,
    )

    async def send_thunk():
        result = await transport.send(
            OutboundMessage(chat_id=chat_id, text="delegate-connectors live e2e")
        )
        return {
            "message_id": result.message_id,
            "chat_id": result.chat_id,
            "ok": result.ok,
        }

    envelope = await composed.connector.write(
        send_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    # A real Telegram send returns an integer message_id; the audited envelope
    # verifies. Direct-verify idiom (mirrors whatsapp's roundtrip test): verify
    # the signature directly over the actual signed canonical_bytes, with NO
    # masking `or`. (The `verify_action_envelope` helper re-derives bytes from
    # payload + observed_at; observed_at is not echoed in the payload, so it is
    # exercised in the Tier-1 unit suite where the timestamp boundary is recorded.)
    assert isinstance(envelope.payload["message_id"], int)
    assert composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )
