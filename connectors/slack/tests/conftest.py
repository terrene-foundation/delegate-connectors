# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for the Slack connector test suite.

Loads ``.env`` (if present) so Tier-2/3 integration tests can read the Slack bot
token + API base URL from the environment. Tier-1 unit tests are pure-Python and
do not require any of this.
"""

from __future__ import annotations

try:  # python-dotenv is a [test] extra; load .env when available.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv optional
    pass
