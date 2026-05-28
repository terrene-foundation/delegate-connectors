# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the Telegram Bot API transport.

Network is stubbed ONLY at the ``httpx`` boundary (a transport-level mock that
captures the request and produces a canned response). The construction
boundary (:class:`OutboundMessage.__post_init__`), env-driven config, and the
typed-error surface for ``429`` are exercised against the real transport
implementation — no mock of the transport itself.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from delegate_connectors.telegram.transport import (
    InboundUpdate,
    OutboundMessage,
    RateLimitedError,
    SendResult,
    TelegramConfig,
    TelegramConfigError,
    TelegramTransport,
    TelegramTransportError,
)
from delegate_connectors.telegram.validation import MessageValidationError

# Pytest auto-asyncio mode (per pyproject.toml [tool.pytest.ini_options]) makes
# every async def test an asyncio test automatically; no module-level mark
# needed (and a module-level @pytest.mark.asyncio would warn on sync tests).


# ── TelegramConfig: env handling ────────────────────────────────────────


def test_config_from_env_requires_bot_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_API_BASE", "https://api.telegram.org")
    with pytest.raises(TelegramConfigError, match="TELEGRAM_BOT_TOKEN"):
        TelegramConfig.from_env()


def test_config_from_env_requires_api_base(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "111111:AAAA")
    monkeypatch.delenv("TELEGRAM_API_BASE", raising=False)
    with pytest.raises(TelegramConfigError, match="TELEGRAM_API_BASE"):
        TelegramConfig.from_env()


def test_config_from_env_rejects_empty_value(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_API_BASE", "https://api.telegram.org")
    with pytest.raises(TelegramConfigError, match="TELEGRAM_BOT_TOKEN"):
        TelegramConfig.from_env()


def test_config_from_env_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "111111:AAAA")
    monkeypatch.setenv("TELEGRAM_API_BASE", "https://api.telegram.org/")
    cfg = TelegramConfig.from_env()
    assert cfg.api_base == "https://api.telegram.org"
    assert cfg.bot_token == "111111:AAAA"


def test_config_repr_does_not_leak_bot_token():
    cfg = TelegramConfig(bot_token="secret-bot-token-XYZ", api_base="https://api.x")
    text = repr(cfg)
    assert "secret-bot-token-XYZ" not in text
    assert "<redacted>" in text


async def test_transport_send_does_not_log_bot_token(caplog):
    """The bot token (in the URL path) MUST NEVER reach a log record."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 7, "chat": {"id": 42}, "text": "hi"},
            },
        )

    transport = httpx.MockTransport(handler)
    cfg = TelegramConfig(bot_token="secret-bot-token-XYZ", api_base="https://api.x")
    async with httpx.AsyncClient(transport=transport) as client:
        tg = TelegramTransport(cfg, client=client)
        with caplog.at_level(
            logging.INFO, logger="delegate_connectors.telegram.transport"
        ):
            await tg.send(OutboundMessage(chat_id=42, text="hi"))
    # The endpoint used the token (sanity check the boundary actually fired).
    assert "secret-bot-token-XYZ" in str(captured["url"])
    # But NO log line carries the token (or the URL).
    for record in caplog.records:
        rendered = (
            record.getMessage()
            + " "
            + json.dumps(getattr(record, "__dict__", {}), default=str)
        )
        assert "secret-bot-token-XYZ" not in rendered


# ── OutboundMessage: Wave-1 validators invoked at construction ──────────


def test_outbound_message_rejects_control_char_text():
    """OutboundMessage.__post_init__ MUST call validate_text (Wave-1)."""
    with pytest.raises(MessageValidationError, match="control"):
        OutboundMessage(chat_id=42, text="hi\rthere")


def test_outbound_message_rejects_empty_text():
    with pytest.raises(MessageValidationError, match="empty"):
        OutboundMessage(chat_id=42, text="")


def test_outbound_message_rejects_over_length_text():
    with pytest.raises(MessageValidationError, match="UTF-16"):
        OutboundMessage(chat_id=42, text="a" * 4097)


def test_outbound_message_rejects_malformed_chat_id():
    """OutboundMessage.__post_init__ MUST call validate_chat_id (Wave-1)."""
    with pytest.raises(MessageValidationError, match="chat_id"):
        OutboundMessage(chat_id="not-an-id-and-no-@", text="hi")


def test_outbound_message_rejects_bool_chat_id():
    with pytest.raises(MessageValidationError, match="bool"):
        OutboundMessage(chat_id=True, text="hi")


def test_outbound_message_accepts_int_chat_id_and_text():
    m = OutboundMessage(chat_id=42, text="hello")
    assert m.to_body() == {"chat_id": 42, "text": "hello"}


def test_outbound_message_accepts_channel_handle():
    m = OutboundMessage(chat_id="@my_channel", text="hello")
    assert m.to_body() == {"chat_id": "@my_channel", "text": "hello"}


# ── send: structured SendResult + httpx boundary ────────────────────────


async def test_send_returns_structured_send_result():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body == {"chat_id": 42, "text": "hi"}
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 7, "chat": {"id": 42}, "text": "hi"},
            },
        )

    transport = httpx.MockTransport(handler)
    tg = TelegramTransport(
        TelegramConfig(bot_token="t", api_base="https://api.x"),
        client=httpx.AsyncClient(transport=transport),
    )
    result = await tg.send(OutboundMessage(chat_id=42, text="hi"))
    assert isinstance(result, SendResult)
    assert result.message_id == 7
    assert result.chat_id == 42
    assert result.ok is True


async def test_send_429_with_parameters_retry_after_maps_to_rate_limited_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 30",
                "parameters": {"retry_after": 30},
            },
        )

    transport = httpx.MockTransport(handler)
    tg = TelegramTransport(
        TelegramConfig(bot_token="t", api_base="https://api.x"),
        client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(RateLimitedError) as excinfo:
        await tg.send(OutboundMessage(chat_id=42, text="hi"))
    assert excinfo.value.retry_after == 30
    # The description from the Bot API surfaces on the typed error.
    assert "Too Many Requests" in str(excinfo.value)


async def test_send_429_legacy_top_level_retry_after_maps_to_rate_limited_error():
    """Some Bot API responses put retry_after at the top level (legacy shape)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "retry_after": 7,
                "description": "slow",
            },
        )

    transport = httpx.MockTransport(handler)
    tg = TelegramTransport(
        TelegramConfig(bot_token="t", api_base="https://api.x"),
        client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(RateLimitedError) as excinfo:
        await tg.send(OutboundMessage(chat_id=42, text="hi"))
    assert excinfo.value.retry_after == 7


async def test_send_non_2xx_other_than_429_raises_generic_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": "Bad Request: chat not found",
            },
        )

    transport = httpx.MockTransport(handler)
    tg = TelegramTransport(
        TelegramConfig(bot_token="t", api_base="https://api.x"),
        client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(TelegramTransportError) as excinfo:
        await tg.send(OutboundMessage(chat_id=42, text="hi"))
    assert "HTTP 400" in str(excinfo.value)
    # Generic transport error MUST NOT be a RateLimitedError.
    assert not isinstance(excinfo.value, RateLimitedError)


# ── get_updates: long-poll + InboundUpdate projection ───────────────────


async def test_get_updates_returns_normalized_inbound_updates():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "getUpdates" in str(request.url)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "message": {
                            "message_id": 5,
                            "chat": {"id": 42},
                            "from": {"id": 9},
                            "text": "hello",
                        },
                    },
                    {"update_id": 101},  # non-message update; fields normalize to None.
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    tg = TelegramTransport(
        TelegramConfig(bot_token="t", api_base="https://api.x"),
        client=httpx.AsyncClient(transport=transport),
    )
    updates = await tg.get_updates(offset=100, timeout=0)
    assert [type(u) for u in updates] == [InboundUpdate, InboundUpdate]
    assert updates[0].update_id == 100
    assert updates[0].message_id == 5
    assert updates[0].chat_id == 42
    assert updates[0].from_user_id == 9
    assert updates[0].text == "hello"
    # Non-message update normalizes to update_id only.
    assert updates[1].update_id == 101
    assert updates[1].message_id is None
    assert updates[1].chat_id is None


async def test_get_updates_429_raises_rate_limited_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"ok": False, "parameters": {"retry_after": 2}, "description": "slow"},
        )

    transport = httpx.MockTransport(handler)
    tg = TelegramTransport(
        TelegramConfig(bot_token="t", api_base="https://api.x"),
        client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(RateLimitedError) as excinfo:
        await tg.get_updates(offset=0, timeout=0)
    assert excinfo.value.retry_after == 2
