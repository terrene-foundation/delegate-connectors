# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-2/3 integration: real SMTP send through the connector against Mailpit.

NO mocks at the boundary — the send transits a real SMTP server. Arrival is
confirmed via Mailpit's REST API (the message genuinely landed), and the
connector's `write` path produces a receipt that verifies under the real
Ed25519Verifier. The connector's IMAP fetch path is covered by a sibling test
that skips when no IMAP server is available (Mailpit ships none — journal 0007).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid

import pytest

from delegate_connectors.email.compose import build_email_runtime
from delegate_connectors.email.imap import ImapConfig, ImapTransport
from delegate_connectors.email.smtp import OutboundMessage, SmtpConfig, SmtpTransport

from _mailpit import (
    IMAP_PORT,
    MAILPIT_HOST,
    SMTP_PORT,
    requires_imap_server,
    requires_mailpit_smtp,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _mailpit_search(api_base: str, subject: str) -> list[dict]:
    url = f"{api_base}/api/v1/search?query={urllib.parse.quote('subject:' + subject)}"
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        data = json.load(resp)
    return data.get("messages", [])


@requires_mailpit_smtp
async def test_connector_write_sends_real_message_arriving_in_mailpit(mailpit_api_base):
    """The connector's audited write path sends a message that lands in Mailpit."""
    smtp = SmtpTransport(SmtpConfig(host=MAILPIT_HOST, port=SMTP_PORT))
    imap = ImapTransport(ImapConfig(host=MAILPIT_HOST, port=IMAP_PORT))
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )
    connector = composed.connector
    subject = "smtp-roundtrip-" + uuid.uuid4().hex[:10]

    async def send_thunk():
        result = await smtp.send(
            OutboundMessage(
                sender="alice@example.com",
                recipient="bob@example.com",
                subject=subject,
                body="real send through Mailpit",
            )
        )
        return {
            "message_id": result.message_id,
            "accepted": result.accepted,
            "recipient": result.recipient,
        }

    # Audited write: the SMTP send is the external side-effect.
    envelope = await connector.write(
        send_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    # The send transited a REAL SMTP server — confirm via Mailpit's REST API.
    found = _mailpit_search(mailpit_api_base, subject)
    assert len(found) == 1, f"message not found in Mailpit for subject={subject!r}"
    assert found[0]["From"]["Address"] == "alice@example.com"
    assert found[0]["To"][0]["Address"] == "bob@example.com"

    # The receipt is non-empty and verifies under the real Ed25519Verifier.
    assert envelope.signature and envelope.canonical_bytes
    assert composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )


@requires_imap_server
async def test_connector_read_round_trips_via_imap(mailpit_api_base):
    """Send via SMTP, then fetch it back via the connector's IMAP read path.

    Skips when no IMAP server is reachable (Mailpit v1.30.0 ships none —
    journal 0007). When a real IMAP server IS available this asserts the full
    inbound round-trip + a verifiable AttestedReadReceipt.
    """
    import asyncio

    smtp = SmtpTransport(SmtpConfig(host=MAILPIT_HOST, port=SMTP_PORT))
    imap = ImapTransport(ImapConfig(host=MAILPIT_HOST, port=IMAP_PORT))
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )
    subject = "imap-roundtrip-" + uuid.uuid4().hex[:10]
    await smtp.send(
        OutboundMessage(
            sender="alice@example.com",
            recipient="bob@example.com",
            subject=subject,
            body="inbound round-trip body",
        )
    )

    async def fetch_thunk():
        for _ in range(10):
            msgs = await imap.fetch("ALL")
            match = [m for m in msgs if m.subject == subject]
            if match:
                return match
            await asyncio.sleep(0.5)
        return []

    messages, receipt = await composed.connector.read(
        fetch_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    assert len(messages) == 1
    assert messages[0].from_addr == "alice@example.com"
    assert messages[0].subject == subject
    assert receipt.attestation and receipt.canonical_bytes
    assert composed.verifier.verify(
        receipt.canonical_bytes,
        receipt.attestation,
        str(composed.identity.delegate_id),
    )
