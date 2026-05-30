# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — shipped outbound validation at the construction boundary.

Tests ONLY the validation Slack v0 actually ships (per ``rules/spec-accuracy.md`` —
test only shipped behavior, do not invent unshipped checks). The shipped
construction boundary is :class:`OutboundSlackMessage.__post_init__` (ADR-S3):

1. ``channel`` is shape-validated via ``normalize_slack_id`` — a malformed channel
   id raises :class:`SlackFieldError` at construction, BEFORE any post.
2. ``text`` is mrkdwn-escaped (NOT rejected) — an injected ``<@U…>`` mention /
   ``<!channel>`` broadcast / ``<url|label>`` link becomes inert text.

On the ``invoke`` hot path the boundary fires inside ``invoke`` (which builds an
``OutboundSlackMessage``), so a malformed channel raises and ZERO
``chat.postMessage`` fires — the behavioral assertion is the double's recorded
zero-post count.

NOTE: there is NO oversized-text / control-char rejection in Slack v0 (Slack's API
tolerates them, and the escape boundary handles the render-injection vector). This
suite does NOT invent those checks — it covers what IS shipped.

Behavioral: construct / invoke the real objects; assert the raise + the double's
post count. NEVER source-grep.
"""

from __future__ import annotations

import pytest

from delegate_connectors.slack.messages import (
    OutboundSlackMessage,
    SlackFieldError,
    escape_mrkdwn,
)

from .conftest import CHANNEL_ID

# Module mark is regression only. The asyncio mark is applied per-function to the
# single async test below — applying it module-wide would tag the three sync
# construction-boundary tests with @pytest.mark.asyncio, which pytest-asyncio
# (strict) flags with a PytestWarning ("marked with asyncio but not an async
# function"). Per-function marking keeps the suite warning-clean.
pytestmark = pytest.mark.regression


# ── construction-boundary validation (shipped) ─────────────────────────────


def test_malformed_channel_raises_at_construction():
    """A malformed channel id raises SlackFieldError at the construction boundary."""
    with pytest.raises(SlackFieldError, match="malformed Slack id"):
        OutboundSlackMessage(channel="not-a-valid-channel", text="hi")


def test_lowercase_channel_raises_case_significant():
    """Slack ids are case-significant — a lowercase id is malformed (not coerced)."""
    with pytest.raises(SlackFieldError):
        OutboundSlackMessage(channel="c0123456789", text="hi")


def test_text_is_mrkdwn_escaped_not_rejected():
    """An injected mention is ESCAPED (inert), not rejected — the shipped behavior."""
    msg = OutboundSlackMessage(channel=CHANNEL_ID, text="<@U07ABCDE123> <!channel>")
    assert msg.text == "&lt;@U07ABCDE123&gt; &lt;!channel&gt;"
    # The escape helper is order-safe: & is escaped first, no double-escaping.
    assert escape_mrkdwn("a & <b>") == "a &amp; &lt;b&gt;"


# ── hot-path: malformed channel → typed error BEFORE any post ──────────────


@pytest.mark.asyncio
async def test_invoke_malformed_channel_rejects_before_any_post(slack):
    """A malformed channel on the invoke hot path raises and ZERO posts fire.

    The known identity authenticates (so this is NOT an auth Reject), then the
    OutboundSlackMessage construction inside invoke raises SlackFieldError BEFORE
    the transport post — the double records zero posts.
    """
    conn = slack["connector"]
    identity = slack["identity"]
    envelope = slack["envelope"]
    double = slack["double"]

    with pytest.raises(SlackFieldError, match="malformed Slack id"):
        await conn.invoke(
            {"channel": "bad-channel-id", "text": "hi"},
            identity=identity,
            envelope=envelope,
        )

    # The validation fired BEFORE the transport post.
    assert double.posts == [], "a malformed-channel Reject MUST fire BEFORE the post"
    assert conn.ledger.records == ()
