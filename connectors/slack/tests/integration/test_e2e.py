# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-2/3 e2e: compose a DelegateRuntime and drive it against the Slack double.

The end-to-end ``runtime.execute()`` OUTCOME assertion (a COMPLETED run carrying a
verifiable SignedActionEnvelope) is GATED on an SDK fix: the shipped
``kailash.delegate`` runtime audit-emit path signs the event PAYLOAD bytes while
``AuditChainEngine.emit_event`` verifies the FULL audit-entry signing bytes, so
``execute()`` fails at the first phase transition under ANY real verifier
(kailash-py#1182, compose.py module docstring "KNOWN SDK BLOCKER"). The outcome
assertion is a STRICT xfail — when the SDK ships the fix it flips to XPASS and
forces the marker's removal.

Intra-impl receipt determinism is asserted SEPARATELY via
``assert_receipts_agree``: it holds regardless of the phase outcome (both runs
reach the SAME deterministic outcome because the double returns a stable ts for an
identical channel+text), which is exactly the cross-impl-agreement contract the
spec asks v0 to demonstrate.

This is Tier-2 against the in-process protocol-faithful Slack Web API double over
a real socket (ADR-S4). The opt-in Tier-3 live Slack workspace test lives below
behind the ``requires_live_slack`` gate — it SKIPS with a "cannot execute" reason
when no live ``SLACK_*`` creds are present, never a mock.
"""

from __future__ import annotations

import json

import pytest

from kailash.delegate import assert_receipts_agree

from delegate_connectors.slack.compose import build_slack_runtime
from delegate_connectors.slack.connector import verify_action_envelope
from delegate_connectors.slack.web_api import SlackTransport, SlackWebConfig

from _slack_api_double import CHANNEL_ID, SENDER_SLACK_ID, TEST_BOT_TOKEN
from _live_slack import requires_live_slack

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _composed(slack_api_double):
    """Build the real composed runtime with the transport pointed at the double."""
    config = SlackWebConfig(
        bot_token=TEST_BOT_TOKEN, base_url=slack_api_double.base_url
    )
    transport = SlackTransport(config)
    return build_slack_runtime(
        transport=transport,
        sender_slack_id=SENDER_SLACK_ID,
    )


def _post_payload() -> dict[str, str]:
    return {"channel": CHANNEL_ID, "text": "e2e post"}


async def test_connector_write_path_carries_verifiable_envelope(slack_api_double):
    """The composed connector's audited write path produces a verifiable envelope.

    Independent of the SDK ``execute()`` blocker: drive the connector's own
    audited ``invoke`` path (authenticate-first → ``write``) and confirm the post
    landed, then re-sign-verify a standalone ``write`` under the composed real
    verifier — the end-to-end trust property the connector ships today.
    """
    composed = _composed(slack_api_double)

    result = await composed.connector.invoke(
        _post_payload(),
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    # The post landed at the double over the real socket.
    recorded = slack_api_double.last_post
    assert recorded.channel == CHANNEL_ID
    assert recorded.text == "e2e post"
    assert result.payload["ok"] is True
    assert result.payload["ts"] == recorded.ts

    # A fresh standalone write through the composed connector verifies under the
    # composed verifier (full identity-bound signing).
    async def thunk():
        return {"ok": True, "ts": recorded.ts, "channel": CHANNEL_ID}

    envelope = await composed.connector.write(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    observed_at = json.loads(envelope.canonical_bytes.decode("utf-8"))["observed_at"]
    assert verify_action_envelope(envelope, composed.verifier, observed_at=observed_at)


async def test_runtime_execute_e2e_against_double_completes(slack_api_double):
    """End-to-end run completes against the socket double on kailash >= 2.28.0.

    Was strict-xfailed on kailash-py#1182 (audit-emit signed payload bytes while
    AuditChainEngine verified full entry bytes; execute() failed at the first
    phase transition). Fixed at <= 2.28.1 (workspaces/whatsapp/journal/0008); the
    marker is removed and the run now completes carrying a dispatch result.
    """
    composed = _composed(slack_api_double)
    result = await composed.runtime.execute(_post_payload())
    assert result.taod_state.phase == "completed"
    assert result.dispatch_result is not None


async def test_runtime_execute_is_deterministic_across_two_runs(slack_api_double):
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
    payload = _post_payload()
    r1 = await _composed(slack_api_double).runtime.execute(dict(payload))
    r2 = await _composed(slack_api_double).runtime.execute(dict(payload))

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


@requires_live_slack
async def test_live_slack_workspace(monkeypatch):
    """Tier-3 LIVE: post a real message to a live Slack workspace channel.

    Opt-in only — SKIPS with a "cannot execute" reason when no live ``SLACK_*``
    creds are present. NEVER a mock fallback: absent creds, the test does not run.
    When it runs, it builds the REAL SlackTransport from env (no injected base URL
    → the live Slack API) and asserts a real ts comes back through the audited
    write path.
    """
    import os

    channel = os.environ["SLACK_LIVE_E2E_CHANNEL"]
    # Real transport: SLACK_API_BASE_URL is unset for the live run so the SDK's
    # default Slack URL is used.
    monkeypatch.delenv("SLACK_API_BASE_URL", raising=False)
    transport = SlackTransport.from_env()
    composed = build_slack_runtime(
        transport=transport,
        sender_slack_id=os.environ.get("SLACK_LIVE_E2E_SENDER", SENDER_SLACK_ID),
    )

    result = await composed.connector.invoke(
        {"channel": channel, "text": "delegate-connector-slack live e2e"},
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    # A real Slack post returns a ts; the audited payload reports it.
    assert result.payload["ok"] is True
    assert result.payload["ts"]
