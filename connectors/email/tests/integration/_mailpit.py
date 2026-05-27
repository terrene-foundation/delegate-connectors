# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Real-infra reachability gates for the integration tier.

Tier-2/3 use REAL infrastructure (a running Mailpit container) — no mocks at
the boundary. Tests skip with a CLEAR reason when the infra is not reachable
(`test-skip-discipline`: "cannot execute", not a masked failure). Mailpit
v1.30.0 ships no IMAP server (journal 0007), so the IMAP-dependent gate skips
honestly rather than failing on a missing server.
"""

from __future__ import annotations

import asyncio
import os
import socket
import urllib.error
import urllib.request

import pytest

MAILPIT_HOST = os.environ.get("EMAIL_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "1025"))
IMAP_PORT = int(os.environ.get("EMAIL_IMAP_PORT", "1143"))
API_BASE = os.environ.get("MAILPIT_API_BASE", "http://localhost:8025")


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _imap_greets(host: str, port: int, timeout: float = 3.0) -> bool:
    """True iff an IMAP server answers the protocol hello on (host, port)."""
    from aioimaplib import aioimaplib

    async def _probe() -> bool:
        client = aioimaplib.IMAP4(host=host, port=port, timeout=timeout)
        try:
            await client.wait_hello_from_server()
            return True
        except Exception:
            return False
        finally:
            try:
                await client.logout()
            except Exception:
                pass

    if not _tcp_open(host, port, timeout=1.0):
        return False
    try:
        return asyncio.run(_probe())
    except Exception:
        return False


MAILPIT_SMTP_REACHABLE = _tcp_open(MAILPIT_HOST, SMTP_PORT)
MAILPIT_API_REACHABLE = _http_ok(f"{API_BASE}/api/v1/info")
IMAP_SERVER_AVAILABLE = _imap_greets(MAILPIT_HOST, IMAP_PORT)

requires_mailpit_smtp = pytest.mark.skipif(
    not (MAILPIT_SMTP_REACHABLE and MAILPIT_API_REACHABLE),
    reason=(
        "cannot execute: Mailpit SMTP + REST API not reachable. Start it with "
        "`docker compose -f connectors/email/docker-compose.yml up -d`."
    ),
)
requires_imap_server = pytest.mark.skipif(
    not IMAP_SERVER_AVAILABLE,
    reason=(
        "cannot execute: no IMAP server answering on the IMAP port. Mailpit "
        "v1.30.0 ships no IMAP server (see workspaces/email/journal/0007-GAP-*); "
        "provision a real IMAP server (e.g. GreenMail) to run this test."
    ),
)
