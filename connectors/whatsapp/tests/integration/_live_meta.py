# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-3 live-Meta reachability gate (importable by the test modules).

Mirrors email's ``_mailpit`` module: the skip predicate lives here (not in
``conftest.py``) so the test modules can ``from _live_meta import
requires_live_meta`` — a sibling ``conftest`` is NOT importable by name from a
test module (it resolves to the nearest conftest on the path, the top-level one).

Tier-2 runs against the in-process protocol-faithful Cloud API double (no
local WhatsApp server exists, unlike email's Mailpit — the double IS the
real-infra surrogate per WA-ADR-5). Tier-3 runs against the real Meta Cloud
API sandbox and is OPT-IN: it skips with a CLEAR "cannot execute" reason when
no live ``WHATSAPP_*`` credentials are present (journal 0003 Gap A;
``test-skip-discipline`` — a skip, never a mock fallback).

A live credential set is distinguished from the Tier-2 test defaults by an
explicit opt-in env var ``WHATSAPP_LIVE_E2E=1`` plus a real access token /
phone-number-id pair that does NOT match the deterministic test fixtures. A
test-default token is treated as ABSENT for the live gate — the live e2e
NEVER fires against the double masquerading as Meta.
"""

from __future__ import annotations

import os

import pytest

# The deterministic test-only credential values from the top-level conftest.
# A live run MUST supply values different from these; matching values means
# "no live creds present" and the Tier-3 test skips with "cannot execute".
_TEST_DEFAULT_ACCESS_TOKEN = "test-access-token-not-a-real-bearer"
_TEST_DEFAULT_PHONE_NUMBER_ID = "100000000000000"


def _live_creds_present() -> bool:
    """True iff a real Meta Cloud API sandbox credential set is configured.

    Requires the explicit ``WHATSAPP_LIVE_E2E=1`` opt-in AND a real access
    token + phone-number-id + recipient that are NOT the Tier-2 test defaults.
    Anything short of all four → the live e2e skips (never a mock fallback).
    """
    if os.environ.get("WHATSAPP_LIVE_E2E") != "1":
        return False
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN") or ""
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or ""
    recipient = os.environ.get("WHATSAPP_LIVE_E2E_RECIPIENT") or ""
    if not token or token == _TEST_DEFAULT_ACCESS_TOKEN:
        return False
    if not phone_id or phone_id == _TEST_DEFAULT_PHONE_NUMBER_ID:
        return False
    if not recipient:
        return False
    return True


LIVE_META_CREDS_PRESENT = _live_creds_present()

requires_live_meta = pytest.mark.skipif(
    not LIVE_META_CREDS_PRESENT,
    reason=(
        "cannot execute: no live WHATSAPP_* creds. The Tier-3 live Meta Cloud "
        "API sandbox test is opt-in (journal 0003 Gap A). Set WHATSAPP_LIVE_E2E=1 "
        "plus real WHATSAPP_ACCESS_TOKEN + WHATSAPP_PHONE_NUMBER_ID + "
        "WHATSAPP_LIVE_E2E_RECIPIENT (all distinct from the Tier-2 test defaults). "
        "Absent these, the test SKIPS — it never falls back to a mock."
    ),
)
