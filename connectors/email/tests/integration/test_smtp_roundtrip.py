# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-2/3 integration: real SMTP send + real IMAP fetch through the connector.

NO mocks at the boundary. Two real servers (see ``docker-compose.yml``):

- **Mailpit** — the outbound send transits a real SMTP server; arrival is
  confirmed via Mailpit's REST API, and the connector's `write` path produces a
  receipt that verifies under the real Ed25519Verifier.
- **GreenMail** — backs the inbound round-trip: send via GreenMail SMTP, then
  fetch the delivered message back via GreenMail IMAP through the connector's
  `read` path (Mailpit v1.30.0 ships no IMAP server — journal 0007).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid

import pytest

from delegate_connectors.email.compose import build_email_runtime
from delegate_connectors.email.connector import verify_read_receipt
from delegate_connectors.email.imap import ImapConfig, ImapTransport
from delegate_connectors.email.smtp import OutboundMessage, SmtpConfig, SmtpTransport

from _mailpit import (
    GREENMAIL_HOST,
    GREENMAIL_IMAP_PORT,
    GREENMAIL_SMTP_PORT,
    IMAP_PORT,
    MAILPIT_HOST,
    SMTP_PORT,
    requires_greenmail,
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


@requires_greenmail
async def test_connector_read_round_trips_via_imap():
    """Send via GreenMail SMTP, then fetch it back via the connector's IMAP read.

    Runs against GreenMail (real SMTP 3025 + real IMAP 3143) — Mailpit v1.30.0
    ships no IMAP server (journal 0007). The send delivers to bob@example.com;
    the IMAP transport logs in AS bob (GreenMail auto-creates the mailbox on
    first login under auth.disabled) and SELECTs the INBOX. Asserts the full
    inbound round-trip + a verifiable, identity-bound AttestedReadReceipt.
    """
    import asyncio

    recipient = "bob@example.com"
    smtp = SmtpTransport(SmtpConfig(host=GREENMAIL_HOST, port=GREENMAIL_SMTP_PORT))
    # Log in to IMAP as the recipient so SELECT INBOX resolves bob's mailbox.
    imap = ImapTransport(
        ImapConfig(
            host=GREENMAIL_HOST,
            port=GREENMAIL_IMAP_PORT,
            username=recipient,
            password="greenmail-any",  # auth.disabled: any password accepted
        )
    )
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )
    subject = "imap-roundtrip-" + uuid.uuid4().hex[:10]
    await smtp.send(
        OutboundMessage(
            sender="alice@example.com",
            recipient=recipient,
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
    # Raw signature verifies under the real Ed25519Verifier ...
    assert composed.verifier.verify(
        receipt.canonical_bytes,
        receipt.attestation,
        str(composed.identity.delegate_id),
    )
    # ... and the full identity-bound receipt (L2 fix) verifies: the manifest
    # re-derived from the fetched messages matches the signed canonical bytes.
    manifest = {
        "count": len(messages),
        "message_ids": [m.message_id for m in messages],
    }
    assert verify_read_receipt(receipt, manifest, composed.verifier) is True
