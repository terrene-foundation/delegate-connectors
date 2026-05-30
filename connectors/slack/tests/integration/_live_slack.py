# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-3 live-Slack reachability gate (importable by the test modules).

Mirrors WhatsApp's ``_live_meta`` + email's ``_mailpit`` modules: the skip
predicate lives here (not in ``conftest.py``) so the test modules can
``from _live_slack import requires_live_slack`` — a sibling ``conftest`` is NOT
importable by name from a test module (it resolves to the nearest conftest on the
path, the top-level one).

Tier-2 runs against the in-process protocol-faithful Slack Web API double over a
REAL socket (no local Slack server exists — the double IS the real-infra
surrogate per ADR-S4) and ALWAYS runs in CI. Tier-3 runs against a real Slack
workspace and is OPT-IN: it skips with a CLEAR "cannot execute" reason when no
live ``SLACK_*`` credentials are present (``test-skip-discipline`` — a skip, never
a mock fallback; the reason is "cannot execute", not "system broken").

A live credential set is distinguished from the Tier-2 test defaults by an
explicit opt-in env var ``SLACK_LIVE_E2E=1`` plus a real bot token + channel that
do NOT match the deterministic test fixtures. A test-default token is treated as
ABSENT for the live gate — the live e2e NEVER fires against the double
masquerading as Slack.
"""

from __future__ import annotations

import os

import pytest

# The deterministic test-only bot token used by the Tier-2 fixtures. A live run
# MUST supply a value different from this; a matching value means "no live creds
# present" and the Tier-3 test skips with "cannot execute".
_TEST_DEFAULT_BOT_TOKEN = "xoxb-test-not-a-real-bot-token"


def _live_creds_present() -> bool:
    """True iff a real Slack workspace credential set is configured.

    Requires the explicit ``SLACK_LIVE_E2E=1`` opt-in AND a real bot token +
    channel that are NOT the Tier-2 test defaults. Anything short of all three →
    the live e2e skips (never a mock fallback).
    """
    if os.environ.get("SLACK_LIVE_E2E") != "1":
        return False
    token = os.environ.get("SLACK_BOT_TOKEN") or ""
    channel = os.environ.get("SLACK_LIVE_E2E_CHANNEL") or ""
    if not token or token == _TEST_DEFAULT_BOT_TOKEN:
        return False
    if not channel:
        return False
    return True


LIVE_SLACK_CREDS_PRESENT = _live_creds_present()

requires_live_slack = pytest.mark.skipif(
    not LIVE_SLACK_CREDS_PRESENT,
    reason=(
        "cannot execute: no live SLACK_* creds. The Tier-3 live Slack workspace "
        "test is opt-in. Set SLACK_LIVE_E2E=1 plus a real SLACK_BOT_TOKEN + "
        "SLACK_LIVE_E2E_CHANNEL (distinct from the Tier-2 test defaults). Absent "
        "these, the test SKIPS — it never falls back to a mock."
    ),
)
