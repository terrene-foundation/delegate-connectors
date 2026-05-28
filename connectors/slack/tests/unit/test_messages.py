# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the message types + injection boundary (messages.py).

Pure-Python: no Slack Web API client, no I/O. Covers id-shape validation,
mrkdwn escaping, case-significant normalization, and OutboundSlackMessage
immutability + boundary enforcement.
"""

from __future__ import annotations

import dataclasses

import pytest

from delegate_connectors.slack.messages import (
    InboundSlackMessage,
    OutboundSlackMessage,
    SlackFieldError,
    escape_mrkdwn,
    normalize_slack_id,
)


# --- normalize_slack_id: shape validation + case-significance --------------


@pytest.mark.parametrize(
    "valid_id",
    ["U07ABCDE123", "C0123456789", "G1234ABCD", "D012345AB", "W08XYZ7890"],
)
def test_normalize_slack_id_accepts_valid_shapes(valid_id: str):
    assert normalize_slack_id(valid_id) == valid_id


def test_normalize_slack_id_trims_surrounding_whitespace():
    assert normalize_slack_id("  C0123456789  ") == "C0123456789"


def test_normalize_slack_id_is_case_significant_not_lowercased():
    # A valid (uppercase) Slack id round-trips UNCHANGED — normalization does
    # NOT lowercase (the divergence from email's normalize_address). Case is
    # preserved: the returned value still contains its uppercase letters.
    assert normalize_slack_id("U07ABCDE123") == "U07ABCDE123"
    assert normalize_slack_id("C07ABCDE123") != "c07abcde123"
    # A lowercased variant of a real id is itself malformed (Slack ids are
    # uppercase-only) — proving normalization neither lowercases nor accepts a
    # lowercased form as equivalent.
    with pytest.raises(SlackFieldError):
        normalize_slack_id("u07abcde123")


@pytest.mark.parametrize(
    "bad_id",
    [
        "",  # empty
        "lowercase",  # no uppercase-letter prefix shape
        "007ABCDE12",  # leading digit, not a letter
        "U123",  # too short (< 8 chars total)
        "U07ABCDE-1",  # hyphen is not base-34 alnum
        "U07ABCDE 1",  # internal space
        "u07abcde123",  # lowercased — wrong case, fails the uppercase shape
    ],
)
def test_normalize_slack_id_rejects_malformed_ids(bad_id: str):
    with pytest.raises(SlackFieldError):
        normalize_slack_id(bad_id)


def test_normalize_slack_id_rejects_non_str():
    with pytest.raises(SlackFieldError):
        normalize_slack_id(12345)  # type: ignore[arg-type]


# --- escape_mrkdwn: the three metacharacters -------------------------------


def test_escape_mrkdwn_escapes_ampersand_lt_gt():
    assert escape_mrkdwn("a & b < c > d") == "a &amp; b &lt; c &gt; d"


def test_escape_mrkdwn_ampersand_escaped_first_no_double_escape():
    # If '&' were escaped AFTER '<'/'>', the '&' in '&lt;' would be re-escaped to
    # '&amp;lt;'. Escaping '&' first produces the correct '&lt;'.
    assert escape_mrkdwn("<") == "&lt;"
    assert escape_mrkdwn(">") == "&gt;"
    assert escape_mrkdwn("&") == "&amp;"


def test_escape_mrkdwn_neutralizes_injected_mention():
    # An injected user mention cannot render live once escaped.
    assert escape_mrkdwn("<@U123456789>") == "&lt;@U123456789&gt;"


def test_escape_mrkdwn_neutralizes_injected_broadcast():
    # <!channel> / <!here> broadcasts cannot render live once escaped.
    assert escape_mrkdwn("<!channel>") == "&lt;!channel&gt;"


def test_escape_mrkdwn_neutralizes_injected_link():
    # <url|label> link syntax cannot render live once escaped.
    assert (
        escape_mrkdwn("<https://evil.example|click here>")
        == "&lt;https://evil.example|click here&gt;"
    )


# --- OutboundSlackMessage: the construction = validation boundary ----------


def test_outbound_message_valid_inputs_succeed():
    msg = OutboundSlackMessage(channel="C0123456789", text="hello world")
    assert msg.channel == "C0123456789"
    assert msg.text == "hello world"


def test_outbound_message_is_frozen_immutable():
    msg = OutboundSlackMessage(channel="C0123456789", text="hi")
    assert any(f.name == "channel" for f in dataclasses.fields(msg))
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.channel = "C9999999999"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.text = "tampered"  # type: ignore[misc]


def test_outbound_message_malformed_channel_raises():
    with pytest.raises(SlackFieldError):
        OutboundSlackMessage(channel="not-a-channel-id", text="hi")


def test_outbound_message_trims_channel_via_normalize():
    msg = OutboundSlackMessage(channel="  C0123456789 ", text="hi")
    assert msg.channel == "C0123456789"


def test_outbound_message_escapes_text_at_construction():
    # Each of the injection vectors is escaped so it cannot render live, and the
    # stored text is the already-escaped, send-safe value.
    msg = OutboundSlackMessage(
        channel="C0123456789",
        text="<@U123> <!channel> & <https://evil|x>",
    )
    assert "<@U123>" not in msg.text
    assert "<!channel>" not in msg.text
    assert msg.text == ("&lt;@U123&gt; &lt;!channel&gt; &amp; &lt;https://evil|x&gt;")


def test_outbound_message_channel_is_case_significant():
    # Channel id case is preserved (not lowercased) through the boundary: a
    # valid uppercase channel id is stored exactly as given.
    msg = OutboundSlackMessage(channel="C07ABCDE123", text="hi")
    assert msg.channel == "C07ABCDE123"
    assert msg.channel != msg.channel.lower()


# --- InboundSlackMessage: normalized inbound shape -------------------------


def test_inbound_message_carries_normalized_fields():
    inbound = InboundSlackMessage(
        channel="C0123456789",
        ts="1700000000.000100",
        user="U07ABCDE123",
        text="a message <with> raw mrkdwn",
    )
    assert inbound.channel == "C0123456789"
    assert inbound.ts == "1700000000.000100"
    assert inbound.user == "U07ABCDE123"
    # Inbound text is carried verbatim (escaping is an outbound concern).
    assert inbound.text == "a message <with> raw mrkdwn"
