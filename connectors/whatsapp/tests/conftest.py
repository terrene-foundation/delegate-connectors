# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for the WhatsApp connector test suite.

Loads ``.env`` (if present) so any future Tier-2/3 tests can read credentials
from the environment. Tier-1 unit tests are pure-Python: they set the env vars
they need explicitly via monkeypatch and do not depend on a populated ``.env``.
"""

from __future__ import annotations

try:  # python-dotenv is a [test] extra; load .env when available.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv optional
    pass
