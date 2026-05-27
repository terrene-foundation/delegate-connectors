# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Real-infra reachability gates for the integration tier.

Tier-2/3 use REAL infrastructure — no mocks at the boundary. Tests skip with a
CLEAR reason when the infra is not reachable (`test-skip-discipline`: "cannot
execute", not a masked failure).

Two services back the tier (see ``docker-compose.yml``):

- **Mailpit** — real SMTP + a REST search API. Backs the SMTP-arrival assertion
  and the e2e composition test. Mailpit v1.30.0 ships NO IMAP server
  (workspaces/email/journal/0007), so it cannot back the inbound round-trip.
- **GreenMail** — real SMTP (3025) AND real IMAP (3143) in one JVM. Backs the
  inbound IMAP round-trip: send via GreenMail SMTP, fetch back via GreenMail
  IMAP through the connector's ``read`` path.
"""

from __future__ import annotations

import asyncio
import os
import socket
import urllib.error
import urllib.request

import pytest

# --- Mailpit (SMTP + REST) ---
MAILPIT_HOST = os.environ.get("EMAIL_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "1025"))
API_BASE = os.environ.get("MAILPIT_API_BASE", "http://localhost:8025")

# --- GreenMail (real SMTP + real IMAP) ---
GREENMAIL_HOST = os.environ.get("EMAIL_GREENMAIL_HOST", "localhost")
GREENMAIL_SMTP_PORT = int(os.environ.get("EMAIL_GREENMAIL_SMTP_PORT", "3025"))
GREENMAIL_IMAP_PORT = int(os.environ.get("EMAIL_GREENMAIL_IMAP_PORT", "3143"))

# Back-compat alias: the inbound round-trip historically read IMAP_PORT; it now
# points at GreenMail's IMAP port.
IMAP_PORT = GREENMAIL_IMAP_PORT


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
GREENMAIL_SMTP_REACHABLE = _tcp_open(GREENMAIL_HOST, GREENMAIL_SMTP_PORT)
IMAP_SERVER_AVAILABLE = _imap_greets(GREENMAIL_HOST, GREENMAIL_IMAP_PORT)

requires_mailpit_smtp = pytest.mark.skipif(
    not (MAILPIT_SMTP_REACHABLE and MAILPIT_API_REACHABLE),
    reason=(
        "cannot execute: Mailpit SMTP + REST API not reachable. Start it with "
        "`docker compose -f connectors/email/docker-compose.yml up -d`."
    ),
)
requires_greenmail = pytest.mark.skipif(
    not (GREENMAIL_SMTP_REACHABLE and IMAP_SERVER_AVAILABLE),
    reason=(
        "cannot execute: GreenMail SMTP+IMAP not reachable. Mailpit v1.30.0 "
        "ships no IMAP server (workspaces/email/journal/0007-GAP-*), so the "
        "inbound round-trip runs against GreenMail (greenmail/standalone, real "
        "SMTP 3025 + real IMAP 3143). Start it with "
        "`docker compose -f connectors/email/docker-compose.yml up -d`."
    ),
)

# Back-compat alias retained for any importer of the old name.
requires_imap_server = requires_greenmail
