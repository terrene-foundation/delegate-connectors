# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for the WhatsApp connector test suite.

Loads ``.env`` (if present) so any Tier-2/3 tests can read credentials from the
environment. Tier-1 unit tests are pure-Python: they set the env vars they need
explicitly via monkeypatch and do not depend on a populated ``.env``.

Also exposes the in-process protocol-faithful Cloud API double + the
non-secret startup-credential fixtures the Tier-2 round-trip suite needs. The
double itself lives in ``tests/integration/_cloud_api_double.py``; the fixtures
here re-export it so both the integration tier and any future tier can build a
real ``WhatsAppCloudApi`` over a real ``httpx.AsyncClient`` whose byte stream
terminates at the double (NO mock at the boundary, WA-ADR-5).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

try:  # python-dotenv is a [test] extra; load .env when available.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv optional
    pass

# The double lives next to the integration tests; make it importable from the
# top-level conftest so the fixture can construct it.
_INTEGRATION_DIR = Path(__file__).parent / "integration"
if str(_INTEGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_DIR))


# Non-secret, test-only startup credentials. These are NOT real Meta
# credentials — they satisfy the connector's env-only startup gates
# (WHATSAPP_PII_HMAC_KEY, WHATSAPP_APP_SECRET, WHATSAPP_WEBHOOK_VERIFY_TOKEN)
# and the Cloud API config (token + phone-number-id + graph version) so the
# REAL connector construction path runs unmodified against the in-process
# double. Credentials are sourced from the env when present (so a live `.env`
# wins for the Tier-3 path) and otherwise fall back to these deterministic
# test fixtures (invariant 5: from env/fixture, never hardcoded in a test body).
_TEST_ENV_DEFAULTS = {
    "WHATSAPP_PII_HMAC_KEY": "test-pii-hmac-key-not-a-real-secret",
    "WHATSAPP_APP_SECRET": "test-app-secret-not-a-real-secret",
    "WHATSAPP_WEBHOOK_VERIFY_TOKEN": "test-verify-token",
    "WHATSAPP_ACCESS_TOKEN": "test-access-token-not-a-real-bearer",
    "WHATSAPP_PHONE_NUMBER_ID": "100000000000000",
    "WHATSAPP_GRAPH_VERSION": "v18.0",
}


@pytest.fixture
def whatsapp_test_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Ensure the connector's startup-credential env gates are satisfied.

    Sets each ``WHATSAPP_*`` startup credential to its current env value if
    present, else to the deterministic test default. Returns the resolved map
    so a test can read the configured phone-number-id / app secret without
    re-reading ``os.environ``. The PII HMAC key + app secret + webhook verify
    token are the three startup-loud gates the connector + ingest construct
    against; the Cloud API triple is what ``WhatsAppCloudConfig.from_env``
    reads.
    """
    resolved: dict[str, str] = {}
    for key, default in _TEST_ENV_DEFAULTS.items():
        value = os.environ.get(key) or default
        monkeypatch.setenv(key, value)
        resolved[key] = value
    return resolved


@pytest.fixture
def cloud_api_double():
    """A fresh in-process protocol-faithful Meta Cloud API double per test."""
    from _cloud_api_double import CloudApiDouble

    return CloudApiDouble()
