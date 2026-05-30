# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for the Telegram connector test suite.

Loads ``.env`` (if present) so Tier-2/3 integration tests can read the Telegram
bot token + Bot API base URL from the environment. Tier-1 unit tests are
pure-Python and do not require any of this.

Also exposes the package-level ``_telegram_test_env`` fixture (autouse for
Tier-2/3) that satisfies the connector's env-only credential gates
(``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_API_BASE``) via ``monkeypatch.setenv`` —
never hardcoded into a test body beyond the deterministic non-secret test
fixtures here. Credentials are sourced from the env when present (so a live
``.env`` wins for the Tier-3 path) and otherwise fall back to these
deterministic test defaults.
"""

from __future__ import annotations

import os

import pytest

try:  # python-dotenv is a [test] extra; load .env when available.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv optional
    pass


# Non-secret, test-only startup credentials. These are NOT a real bot token —
# they satisfy the transport's env-only config gate (TELEGRAM_BOT_TOKEN +
# TELEGRAM_API_BASE) so the REAL connector construction path runs unmodified
# against the in-process double. The token value is distinct from any live
# credential so the Tier-3 live gate (_live_telegram) treats it as ABSENT.
_TEST_ENV_DEFAULTS = {
    "TELEGRAM_BOT_TOKEN": "test-bot-token-not-a-real-secret",
    "TELEGRAM_API_BASE": "https://api.telegram.org",
}


@pytest.fixture(autouse=True)
def _telegram_test_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Ensure the connector's env-only credential gates are satisfied.

    Sets ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_API_BASE`` to their current env
    value if present, else to the deterministic test default. Autouse so every
    tier's ``TelegramConfig.from_env`` resolves — Tier-1 unit tests build their
    own configs explicitly and are unaffected (setting an env var they ignore is
    a no-op). Credentials come from env/fixture, never hardcoded in a test body.
    """
    resolved: dict[str, str] = {}
    for key, default in _TEST_ENV_DEFAULTS.items():
        value = os.environ.get(key) or default
        monkeypatch.setenv(key, value)
        resolved[key] = value
    return resolved
