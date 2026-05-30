# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Integration-tier fixtures for the Telegram connector.

Defines the in-process Bot API double fixture (`botapi_double`) and the
composed-runtime fixture (`telegram_composed`) the Tier-2 tier consumes. The
double is ALWAYS available (no live Telegram needed), so the integration tests
RUN in CI — they do not skip.

This file guarantees the integration directory is on `sys.path` so the
`_botapi_double` / `_telegram_compose` / `_live_telegram` helper modules import
cleanly even when the suite is invoked directly at the integration directory (a
sibling `conftest` resolves to the nearest conftest on the path, not this file,
and is NOT importable by name — the composed-runtime helpers therefore live in
the importable `_telegram_compose` module).

The startup credentials are set by the package-level autouse `_telegram_test_env`
fixture in `tests/conftest.py` (env-only contract via `monkeypatch.setenv`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)

from _botapi_double import BotApiDouble  # noqa: E402
from _telegram_compose import compose_over_double  # noqa: E402


@pytest.fixture
def botapi_double() -> BotApiDouble:
    """The in-process protocol-faithful Telegram Bot API double (always available)."""
    return BotApiDouble()


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    """A real Ed25519 signing key for the composed runtime."""
    return Ed25519PrivateKey.generate()


@pytest.fixture
async def telegram_composed(
    botapi_double: BotApiDouble, signing_key: Ed25519PrivateKey
):
    """A real composed Telegram runtime over the in-process double.

    Yields the composed runtime and closes the underlying ``httpx.AsyncClient``
    in teardown so no ``ResourceWarning`` (unclosed transport) is emitted.
    """
    client = botapi_double.client()
    composed = compose_over_double(botapi_double, client, signing_key)
    try:
        yield composed
    finally:
        await client.aclose()
