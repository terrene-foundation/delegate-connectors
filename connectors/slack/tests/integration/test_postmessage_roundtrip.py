# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-2 integration: real connector round-trips against the Slack API double.

NO mocks at the boundary. The REAL
:class:`~delegate_connectors.slack.web_api.SlackTransport` (wrapping a REAL
``slack_sdk`` ``AsyncWebClient``) posts over a REAL socket to the in-process
protocol-faithful Slack Web API double (ADR-S4). Real Ed25519 signing key, real
shipped :class:`~kailash.delegate.verifier.Ed25519Verifier`.

Round-trip:

- **Post**: drive the connector ``invoke`` (authenticate-first → audited
  ``write``) path. Assert (a) the message is RECORDED at the double AND visible
  via ``conversations.history`` through the double's OWN history surface (NOT
  connector internal state), and (b) the ``invoke`` result carries the signed
  envelope payload.
- **Read-back**: drive the connector ``read`` path over the same socket; assert
  the ``AttestedReadReceipt`` verifies under the real ``Ed25519Verifier``; tamper
  a bound field → verification fails.
"""

from __future__ import annotations

import dataclasses

import pytest

from delegate_connectors.slack.connector import verify_read_receipt
from delegate_connectors.slack.messages import OutboundSlackMessage

from _slack_api_double import CHANNEL_ID

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_invoke_posts_message_recorded_and_visible_via_history(composed_slack):
    """invoke → chat.postMessage lands at the double AND is visible via history."""
    conn = composed_slack["connector"]
    identity = composed_slack["identity"]
    envelope = composed_slack["envelope"]
    double = composed_slack["double"]

    result = await conn.invoke(
        {"channel": CHANNEL_ID, "text": "hello over the socket"},
        identity=identity,
        envelope=envelope,
    )

    # 1. The post is RECORDED at the double with the Bearer auth + content.
    recorded = double.last_post
    assert recorded.channel == CHANNEL_ID
    assert recorded.text == "hello over the socket"
    assert recorded.authorization == "Bearer xoxb-test-not-a-real-bot-token"

    # 2. The message is visible via the double's OWN conversations.history surface
    #    (NOT connector internal state).
    history = double.history_for(CHANNEL_ID)
    assert len(history) == 1
    assert history[0]["text"] == "hello over the socket"
    assert history[0]["ts"] == recorded.ts

    # 3. The invoke result carries the signed-envelope payload (ok + ts + channel)
    #    and reports the external side effect.
    assert result.external_side_effect is True
    assert result.tenant_id_observed == "t1"
    assert result.payload["ok"] is True
    assert result.payload["ts"] == recorded.ts
    assert result.payload["channel"] == CHANNEL_ID


async def test_read_pulls_message_back_and_receipt_verifies(composed_slack):
    """read pulls the prior post back via history; the receipt verifies."""
    conn = composed_slack["connector"]
    identity = composed_slack["identity"]
    envelope = composed_slack["envelope"]
    transport = composed_slack["transport"]
    verifier = composed_slack["verifier"]
    double = composed_slack["double"]

    # First post a message so history has something to pull back.
    await conn.invoke(
        {"channel": CHANNEL_ID, "text": "read me back"},
        identity=identity,
        envelope=envelope,
    )
    expected_ts = double.last_post.ts

    # The read thunk wraps the REAL transport.history call over the socket.
    async def history_thunk():
        return await transport.history(CHANNEL_ID, limit=100)

    messages, receipt = await conn.read(
        history_thunk, identity=identity, envelope=envelope
    )

    # The message came back over the socket through the real transport.
    assert len(messages) == 1
    assert messages[0].channel == CHANNEL_ID
    assert messages[0].ts == expected_ts
    assert messages[0].text == "read me back"

    # The attested read receipt is NON-EMPTY and verifies under the real verifier.
    # The manifest is re-derived exactly as the connector builds it (channel +
    # count + message_ts ids — never body bytes).
    assert receipt.attestation and receipt.canonical_bytes
    manifest = {
        "channel": CHANNEL_ID,
        "count": len(messages),
        "message_ts": [m.ts for m in messages],
    }
    assert verify_read_receipt(receipt, manifest, verifier) is True

    # Tamper a bound field (attester) → re-derived bytes diverge → fails.
    tampered = dataclasses.replace(receipt, attester_delegate_id="attacker")
    assert verify_read_receipt(tampered, manifest, verifier) is False


async def test_outbound_text_is_mrkdwn_escaped_over_the_wire(composed_slack):
    """A mention-injection payload is escaped at the boundary before the post.

    The OutboundSlackMessage construction boundary escapes ``<@U…>`` so the bytes
    the double receives are inert text — the live render-injection vector is
    closed before the socket write.
    """
    conn = composed_slack["connector"]
    identity = composed_slack["identity"]
    envelope = composed_slack["envelope"]
    double = composed_slack["double"]

    # Sanity: the construction boundary escapes the metacharacters.
    msg = OutboundSlackMessage(channel=CHANNEL_ID, text="<@U07ABCDE123> hi")
    assert msg.text == "&lt;@U07ABCDE123&gt; hi"

    await conn.invoke(
        {"channel": CHANNEL_ID, "text": "<@U07ABCDE123> hi"},
        identity=identity,
        envelope=envelope,
    )
    # The escaped form is what reached the double over the socket.
    assert double.last_post.text == "&lt;@U07ABCDE123&gt; hi"
