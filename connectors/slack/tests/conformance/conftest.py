# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Conformance-tier fixtures. Presence of this conftest.py triggers pytest's
sys.path insertion for ``tests/conformance/`` so the sibling ``loader`` module is
importable without a package wrapper (mirrors the WhatsApp + email conformance
harness pattern)."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
