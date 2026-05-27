# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Integration-tier fixtures. Reachability gates live in ``_mailpit`` so they
can be imported by the test modules; this file only exposes fixtures."""

from __future__ import annotations

import pytest

from _mailpit import API_BASE


@pytest.fixture
def mailpit_api_base() -> str:
    return API_BASE
