# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for runtime composition (compose.py).

These prove compose BUILDS a valid, reusable DelegateRuntime with the real
shipped concretes (no mocks). The end-to-end ``runtime.execute()`` assertion is
gated on an SDK fix (kailash-py#1182 — same SDK failure mode the email connector
reproduces) and is marked xfail with a precise reason — NOT skipped silently and
NOT faked. The connector-level signed write envelope verifies under the composed
verifier as a real pass, not xfail.
"""

from __future__ import annotations

import pytest

from kailash.delegate import DelegateRuntime, DispatchSurface

from delegate_connectors.slack.compose import (
    ComposedSlackRuntime,
    SlackV0Signature,
    build_slack_runtime,
)
from delegate_connectors.slack.web_api import SlackTransport, SlackWebConfig

pytestmark = pytest.mark.asyncio


class _FakeAsyncWebClient:
    """Minimal AsyncWebClient stand-in for the transport seam."""

    def __init__(self):
        self.post_calls: list[dict] = []

    async def chat_postMessage(self, *, channel: str, text: str):
        self.post_calls.append({"channel": channel, "text": text})
        return {"ok": True, "ts": "1700000000.000001", "channel": channel}

    async def conversations_history(self, *, channel: str, limit: int):
        return {"ok": True, "messages": []}


def _transport() -> SlackTransport:
    cfg = SlackWebConfig(bot_token="xoxb-fixture", base_url="http://mock/api/")
    return SlackTransport(cfg, _client=_FakeAsyncWebClient())


# ── Composition (invariants 1-3) ────────────────────────────────────────


async def test_build_slack_runtime_constructs_real_runtime():
    """Invariant 1: real shipped concretes; Ed25519Verifier (not NullVerifier)."""
    composed = build_slack_runtime(
        transport=_transport(), sender_slack_id="U07ABCDE123"
    )
    assert isinstance(composed, ComposedSlackRuntime)
    assert isinstance(composed.runtime, DelegateRuntime)
    assert isinstance(composed.dispatch_surface, DispatchSurface)


async def test_build_slack_runtime_is_reusable_independent_instances():
    """Invariant 4: composed runtime is reusable; no per-call global state."""
    a = build_slack_runtime(transport=_transport(), sender_slack_id="U07AAA1111")
    b = build_slack_runtime(transport=_transport(), sender_slack_id="U07BBB2222")
    assert a.identity.delegate_id != b.identity.delegate_id


async def test_v0_signature_is_the_slack_post_contract():
    """The v0 fixture signature carries the slack-post input/output schema."""
    sig = SlackV0Signature()
    assert sig.name == "slack-post"
    assert set(sig.input_schema) == {"channel", "text"}
    assert set(sig.output_schema) == {"ok", "ts", "channel"}


async def test_connector_receipts_verify_under_composed_verifier():
    """The verifier compose returns verifies the connector's own receipts.

    This is the REAL pass (not xfail) — the runtime-level execute() outcome
    assertion is xfail-gated on kailash-py#1182, but the connector-level
    signed envelope verifies cleanly under the composed Ed25519Verifier.
    """
    composed = build_slack_runtime(
        transport=_transport(), sender_slack_id="U07ABCDE123"
    )

    async def thunk():
        return {"ok": True, "ts": "1700000000.000001", "channel": "C0123456789"}

    envelope = await composed.connector.write(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    assert composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )


@pytest.mark.xfail(
    reason=(
        "SDK bug (kailash.delegate, tracked as kailash-py#1182): runtime/dispatch "
        "audit-emit signs payload bytes but AuditChainEngine verifies the full "
        "entry signing bytes, so runtime.execute() fails at the first phase "
        "transition under any real verifier. See workspaces/email/journal/"
        "0005-GAP-* for the full reproduction — same SDK failure mode reproduces "
        "for slack. The connector's own receipts verify (test above); this is "
        "gated on the SDK fix."
    ),
    strict=True,
)
async def test_runtime_execute_end_to_end_gated_on_sdk_fix():
    """End-to-end ``await runtime.execute(...)`` — xfail on kailash-py#1182.

    When the SDK is fixed this assertion will hold and the xfail flips to
    XPASS (strict=True turns an unexpected pass into a failure, forcing the
    xfail marker to be removed once the SDK ships the fix).
    """
    composed = build_slack_runtime(
        transport=_transport(), sender_slack_id="U07ABCDE123"
    )
    result = await composed.runtime.execute(
        {"channel": "C0123456789", "text": "hello team"}
    )
    assert result.taod_state.phase == "completed"
