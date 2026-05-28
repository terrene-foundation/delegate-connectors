# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the Slack Web API transport (no network).

The SDK boundary (``AsyncWebClient``) is stubbed by injecting a fake client into
:class:`SlackTransport` via the ``_client`` constructor kwarg — exactly the
documented Tier-1 seam. The transport CONTRACT itself (config -> env, payload
shape, response coercion) is not mocked.
"""

from __future__ import annotations

import pytest

from delegate_connectors.slack.messages import (
    OutboundSlackMessage,
    SlackFieldError,
)
from delegate_connectors.slack.web_api import (
    PostResult,
    SlackTransport,
    SlackWebConfig,
    SlackWebConfigError,
)

pytestmark = pytest.mark.asyncio


# ---------- SlackWebConfig.from_env ----------


async def test_slack_web_config_from_env_requires_bot_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with pytest.raises(SlackWebConfigError, match="SLACK_BOT_TOKEN"):
        SlackWebConfig.from_env()


async def test_slack_web_config_from_env_blank_bot_token_is_rejected(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")
    with pytest.raises(SlackWebConfigError, match="SLACK_BOT_TOKEN"):
        SlackWebConfig.from_env()


async def test_slack_web_config_from_env_default_base_url(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token-001")
    monkeypatch.delenv("SLACK_API_BASE_URL", raising=False)
    cfg = SlackWebConfig.from_env()
    assert cfg.bot_token == "xoxb-test-token-001"
    # Default Slack Web API base URL — used in production, replaced by the
    # Tier-2 mock container when SLACK_API_BASE_URL is set.
    assert cfg.base_url == "https://slack.com/api/"


async def test_slack_web_config_from_env_honours_base_url_override(monkeypatch):
    """The Tier-2 mock seam: SLACK_API_BASE_URL retargets the AsyncWebClient."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token-002")
    monkeypatch.setenv("SLACK_API_BASE_URL", "http://slack-mock:8080/api/")
    cfg = SlackWebConfig.from_env()
    assert cfg.base_url == "http://slack-mock:8080/api/"


# ---------- SlackTransport — fake-client stub at the SDK boundary ----------


class _FakeAsyncWebClient:
    """Minimal AsyncWebClient stand-in exposing the two methods we exercise.

    Records every call so the test can assert the request shape AND returns
    plain dict responses (the shape AsyncWebClient.SlackResponse.data has).
    """

    def __init__(self, *, post_response=None, history_response=None):
        self.post_response = post_response or {
            "ok": True,
            "ts": "1234567890.000100",
            "channel": "C0123456789",
        }
        self.history_response = history_response or {
            "ok": True,
            "messages": [
                {"ts": "1700000000.000001", "user": "U07ABCDE123", "text": "hello"},
                {"ts": "1700000001.000002", "user": "U07ABCDE123", "text": "world"},
            ],
        }
        self.post_calls: list[dict] = []
        self.history_calls: list[dict] = []

    async def chat_postMessage(self, *, channel: str, text: str):
        self.post_calls.append({"channel": channel, "text": text})
        return self.post_response

    async def conversations_history(self, *, channel: str, limit: int):
        self.history_calls.append({"channel": channel, "limit": limit})
        return self.history_response


def _transport(client: _FakeAsyncWebClient | None = None) -> SlackTransport:
    cfg = SlackWebConfig(bot_token="xoxb-fixture-token", base_url="http://mock/api/")
    return SlackTransport(cfg, _client=client or _FakeAsyncWebClient())


async def test_transport_rejects_non_config():
    with pytest.raises(TypeError, match="SlackWebConfig"):
        SlackTransport("not-a-config")  # type: ignore[arg-type]


async def test_post_message_sends_correct_call_shape():
    fake = _FakeAsyncWebClient()
    transport = _transport(fake)
    msg = OutboundSlackMessage(channel="C0123456789", text="hello team")
    result = await transport.post_message(msg)
    # SDK boundary received exactly the validated/escaped fields.
    assert len(fake.post_calls) == 1
    assert fake.post_calls[0]["channel"] == "C0123456789"
    assert fake.post_calls[0]["text"] == "hello team"
    assert isinstance(result, PostResult)
    assert result.ok is True
    assert result.ts == "1234567890.000100"


async def test_post_message_propagates_negative_outcome():
    """A Slack ``ok: false`` MUST propagate, not be masked as success."""
    fake = _FakeAsyncWebClient(
        post_response={"ok": False, "error": "channel_not_found"}
    )
    transport = _transport(fake)
    msg = OutboundSlackMessage(channel="C0123456789", text="hi")
    result = await transport.post_message(msg)
    assert result.ok is False


async def test_post_message_requires_outbound_message_type():
    transport = _transport()
    with pytest.raises(TypeError, match="OutboundSlackMessage"):
        await transport.post_message("just a string")  # type: ignore[arg-type]


async def test_post_message_escapes_mrkdwn_at_boundary():
    """The OutboundSlackMessage construction boundary mrkdwn-escapes user text.

    A live ``<@U…>`` mention / ``<!channel>`` broadcast / ``<url|label>`` link
    is inert by the time the SDK boundary sees it. Asserts the injection
    surface is closed at the dataclass boundary, not at transport.
    """
    fake = _FakeAsyncWebClient()
    transport = _transport(fake)
    raw = "ping <@U07ABCDE123> & say <!channel>"
    msg = OutboundSlackMessage(channel="C0123456789", text=raw)
    await transport.post_message(msg)
    sent_text = fake.post_calls[0]["text"]
    assert "<@U07ABCDE123>" not in sent_text
    assert "<!channel>" not in sent_text
    assert "&lt;" in sent_text and "&gt;" in sent_text and "&amp;" in sent_text


async def test_history_returns_bounded_page_inbound_messages():
    fake = _FakeAsyncWebClient()
    transport = _transport(fake)
    messages = await transport.history("C0123456789", limit=50)
    # Bounded page: caller's limit is forwarded; no cursor-pagination loop.
    assert len(fake.history_calls) == 1
    assert fake.history_calls[0] == {"channel": "C0123456789", "limit": 50}
    assert len(messages) == 2
    assert messages[0].channel == "C0123456789"
    assert messages[0].ts == "1700000000.000001"
    assert messages[0].user == "U07ABCDE123"
    assert messages[0].text == "hello"


async def test_history_validates_channel_shape_before_sdk_call():
    """A malformed channel id MUST raise before any SDK call fires."""
    fake = _FakeAsyncWebClient()
    transport = _transport(fake)
    with pytest.raises(SlackFieldError, match="malformed"):
        await transport.history("not-a-slack-id", limit=10)
    # Boundary rejected the call; the SDK never saw it.
    assert fake.history_calls == []


async def test_history_rejects_non_positive_limit():
    transport = _transport()
    with pytest.raises(ValueError, match="positive int"):
        await transport.history("C0123456789", limit=0)
    with pytest.raises(ValueError, match="positive int"):
        await transport.history("C0123456789", limit=-1)


async def test_history_tolerates_empty_messages_payload():
    fake = _FakeAsyncWebClient(history_response={"ok": True, "messages": []})
    transport = _transport(fake)
    messages = await transport.history("C0123456789", limit=10)
    assert messages == []


async def test_history_skips_non_dict_message_entries_defensively():
    """A non-dict entry in the messages array MUST not raise; it is skipped."""
    fake = _FakeAsyncWebClient(
        history_response={
            "ok": True,
            "messages": [
                "not-a-dict",
                {"ts": "1700000000.000001", "user": "U07ABCDE123", "text": "ok"},
            ],
        }
    )
    transport = _transport(fake)
    messages = await transport.history("C0123456789", limit=10)
    assert len(messages) == 1
    assert messages[0].text == "ok"


async def test_no_credential_token_appears_in_post_response_data():
    """Defense-in-depth: the PostResult never carries the bot token through."""
    transport = _transport()
    msg = OutboundSlackMessage(channel="C0123456789", text="hi")
    result = await transport.post_message(msg)
    # The PostResult fields are explicitly ok/ts/channel — no credentials path.
    assert "xoxb" not in repr(result)
