# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression-tier fixtures.

``telegram_regression_composed`` builds the real composed runtime over the
in-process Bot API double (no live Telegram). Reuses the importable composed
helpers in the integration directory's ``_telegram_compose`` module (a sibling
``conftest`` is not importable by name, so the helpers live in a plain module).

The integration directory is placed on ``sys.path`` so ``_botapi_double`` and
``_telegram_compose`` import cleanly from the regression tier too. NO mock at
the connector boundary: the REAL ``TelegramTransport`` runs over a REAL
``httpx.AsyncClient`` whose byte stream terminates at the in-process double
(Protocol-satisfying deterministic adapter per ``rules/testing.md`` §
"Protocol Adapters").
"""

from __future__ import annotations

import sys
from pathlib import Path

_INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "integration"
if str(_INTEGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_DIR))

import pytest  # noqa: E402

from _botapi_double import BotApiDouble  # noqa: E402
from _telegram_compose import compose_fresh  # noqa: E402


@pytest.fixture
def botapi_double() -> BotApiDouble:
    """The in-process protocol-faithful Telegram Bot API double (always available)."""
    return BotApiDouble()


@pytest.fixture
async def telegram_regression_composed(botapi_double: BotApiDouble):
    """A real composed Telegram runtime over the in-process double.

    Yields the composed runtime; closes the underlying ``httpx.AsyncClient`` in
    teardown so no ``ResourceWarning`` (unclosed transport) is emitted. The
    ``botapi_double`` fixture is the SAME instance the test receives, so a test
    can assert on the double's recorded requests after driving the connector.
    """
    composed, client = compose_fresh(botapi_double)
    try:
        yield composed
    finally:
        await client.aclose()
