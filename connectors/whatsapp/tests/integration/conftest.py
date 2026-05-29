# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Integration-tier conftest.

The Cloud API double fixture (`cloud_api_double`) and the startup-credential
fixture (`whatsapp_test_env`) are defined in the package-level
`tests/conftest.py` and inherited here. The Tier-3 live-Meta skip predicate
lives in the importable `_live_meta` module (mirroring email's `_mailpit`) so
the test modules can import it by name — a sibling `conftest` resolves to the
nearest conftest on the path, not this file.

This file only guarantees the integration directory is on `sys.path` so the
`_live_meta` / `_cloud_api_double` helper modules import cleanly even when the
suite is invoked directly at the integration directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
