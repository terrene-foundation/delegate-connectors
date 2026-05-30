# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-3 live-Telegram reachability gate (importable by the test modules).

Mirrors the WhatsApp connector's ``_live_meta`` module: the skip predicate
lives here (not in ``conftest.py``) so the test modules can
``from _live_telegram import requires_live_telegram`` — a sibling ``conftest``
is NOT importable by name from a test module (it resolves to the nearest
conftest on the path, the top-level one).

Tier-2 runs against the in-process protocol-faithful Bot API double (no local
Telegram server exists, unlike email's Mailpit — the double IS the real-infra
surrogate). Tier-3 runs against the real Telegram Bot API and is OPT-IN: it
skips with a CLEAR "cannot execute" reason when no live ``TELEGRAM_*``
credentials are present (``test-skip-discipline`` — a skip, never a mock
fallback).

A live credential set is distinguished from the Tier-2 test defaults by an
explicit opt-in env var ``TELEGRAM_LIVE_E2E=1`` plus a real bot token that does
NOT match the deterministic test fixture. A test-default token is treated as
ABSENT for the live gate — the live e2e NEVER fires against the double
masquerading as Telegram.
"""

from __future__ import annotations

import os

import pytest

# The deterministic test-only credential value the unit/integration suites use.
# A live run MUST supply a token different from this; a matching token means
# "no live creds present" and the Tier-3 test skips with "cannot execute".
_TEST_DEFAULT_BOT_TOKEN = "test-bot-token-not-a-real-secret"


def _live_creds_present() -> bool:
    """True iff a real Telegram Bot API credential set is configured.

    Requires the explicit ``TELEGRAM_LIVE_E2E=1`` opt-in AND a real bot token +
    chat id that are NOT the Tier-2 test defaults. Anything short of all three
    → the live e2e skips (never a mock fallback).
    """
    if os.environ.get("TELEGRAM_LIVE_E2E") != "1":
        return False
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.environ.get("TELEGRAM_LIVE_E2E_CHAT_ID") or ""
    if not token or token == _TEST_DEFAULT_BOT_TOKEN:
        return False
    if not chat_id:
        return False
    return True


LIVE_TELEGRAM_CREDS_PRESENT = _live_creds_present()

requires_live_telegram = pytest.mark.skipif(
    not LIVE_TELEGRAM_CREDS_PRESENT,
    reason=(
        "cannot execute: no live TELEGRAM_* creds. The Tier-3 live Telegram Bot "
        "API test is opt-in. Set TELEGRAM_LIVE_E2E=1 plus a real TELEGRAM_BOT_TOKEN "
        "+ TELEGRAM_LIVE_E2E_CHAT_ID (distinct from the Tier-2 test defaults). "
        "Absent these, the test SKIPS — it never falls back to a mock."
    ),
)
