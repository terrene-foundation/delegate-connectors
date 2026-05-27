# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for the email connector test suite.

Loads ``.env`` (if present) so Tier-2/3 integration tests can read SMTP/IMAP
coordinates from the environment. Tier-1 unit tests are pure-Python and do not
require any of this.
"""

from __future__ import annotations

import os

import pytest

try:  # python-dotenv is a [test] extra; load .env when available.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv optional
    pass


# Mailpit local-dev defaults. Integration tests use these unless the
# environment overrides them.
MAILPIT_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "1025"))
MAILPIT_IMAP_PORT = int(os.environ.get("EMAIL_IMAP_PORT", "1143"))
MAILPIT_HOST = os.environ.get("EMAIL_SMTP_HOST", "localhost")


def _docker_available() -> bool:
    """True iff a Docker daemon is reachable (for the integration-skip gate)."""
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).returncode
            == 0
        )
    except Exception:  # pragma: no cover - defensive
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    return _docker_available()
