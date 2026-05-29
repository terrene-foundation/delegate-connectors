# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the WhatsApp Cloud API transport (no real network).

The ONLY stub boundary is ``httpx.MockTransport`` (WA-ADR-1): the transport's
own ``httpx.AsyncClient`` is driven by a responder so the request the Cloud API
WOULD receive is asserted against the Meta ``POST /messages`` shape, and the
parsed ``SendResult`` is asserted against the response envelope. The
``WhatsAppCloudApi`` class itself is NEVER mocked — it is the real transport.

Credentials are supplied via ``monkeypatch.setenv`` (env-only), never hardcoded.
"""

from __future__ import annotations

import json

import httpx
import pytest

from delegate_connectors.whatsapp.cloud_api import (
    CloudApiConfigError,
    MessageValidationError,
    OutboundMessage,
    RateLimitedError,
    SendResult,
    WhatsAppCloudApi,
    WhatsAppCloudApiError,
    WhatsAppCloudConfig,
)

# A representative recipient and its bare-digit normalization, reused below.
_RAW_TO = "+1 (415) 555-0100"
_DIGITS = "14155550100"


def _config() -> WhatsAppCloudConfig:
    return WhatsAppCloudConfig(
        access_token="EAAG-test-token",
        phone_number_id="1234567890",
        graph_version="18.0",
    )


# ── OutboundMessage.to_body — request body construction ──────────────────


def test_to_body_text_message_shape():
    msg = OutboundMessage(to=_RAW_TO, text="hello there")
    body = msg.to_body()
    assert body == {
        "messaging_product": "whatsapp",
        "to": _DIGITS,
        "type": "text",
        "text": {"body": "hello there"},
    }


def test_to_body_template_message_shape():
    msg = OutboundMessage(
        to=_RAW_TO, template_name="order_update", template_language="en_US"
    )
    body = msg.to_body()
    assert body == {
        "messaging_product": "whatsapp",
        "to": _DIGITS,
        "type": "template",
        "template": {"name": "order_update", "language": {"code": "en_US"}},
    }


def test_outbound_message_normalizes_recipient_at_construction():
    msg = OutboundMessage(to=_RAW_TO, text="x")
    # __post_init__ normalizes the recipient to bare-digit E.164.
    assert msg.to == _DIGITS


def test_outbound_message_requires_exactly_one_of_text_or_template():
    # Neither set → reject.
    with pytest.raises(MessageValidationError, match="exactly one"):
        OutboundMessage(to=_RAW_TO)
    # Both set → reject.
    with pytest.raises(MessageValidationError, match="exactly one"):
        OutboundMessage(to=_RAW_TO, text="x", template_name="t")


def test_outbound_message_rejects_unnormalizable_recipient_without_leaking():
    with pytest.raises(MessageValidationError) as exc:
        OutboundMessage(to="not-a-number", text="x")
    # The raised message MUST NOT echo the raw (potentially-PII) input.
    assert "not-a-number" not in str(exc.value)


# ── WhatsAppCloudConfig.from_env — env-only credentials ──────────────────


def test_config_from_env_reads_all_three(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "999")
    monkeypatch.setenv("WHATSAPP_GRAPH_VERSION", "v19.0")
    cfg = WhatsAppCloudConfig.from_env()
    assert cfg.access_token == "tok"
    assert cfg.phone_number_id == "999"
    # Leading 'v' is stripped so callers may pass either form.
    assert cfg.graph_version == "19.0"


def test_config_from_env_raises_on_missing_token(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "999")
    monkeypatch.setenv("WHATSAPP_GRAPH_VERSION", "18.0")
    with pytest.raises(CloudApiConfigError, match="WHATSAPP_ACCESS_TOKEN"):
        WhatsAppCloudConfig.from_env()


def test_config_from_env_raises_on_missing_phone_number_id(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.setenv("WHATSAPP_GRAPH_VERSION", "18.0")
    with pytest.raises(CloudApiConfigError, match="WHATSAPP_PHONE_NUMBER_ID"):
        WhatsAppCloudConfig.from_env()


def test_config_repr_never_exposes_access_token():
    cfg = _config()
    text = repr(cfg)
    assert "EAAG-test-token" not in text
    assert "redacted" in text


# ── _raise_for_status — typed error mapping ──────────────────────────────


def _response(
    status_code: int, *, body: dict | None = None, headers: dict | None = None
):
    return httpx.Response(
        status_code,
        headers=headers or {},
        content=(json.dumps(body).encode() if body is not None else b""),
        request=httpx.Request("POST", "https://graph.facebook.com/v18.0/1/messages"),
    )


def test_raise_for_status_passes_2xx():
    # No raise on a 2xx response.
    WhatsAppCloudApi._raise_for_status(_response(200, body={"ok": True}))


def test_raise_for_status_maps_429_to_rate_limited_with_header_retry_after():
    resp = _response(
        429,
        body={"error": {"message": "rate limit hit"}},
        headers={"Retry-After": "42"},
    )
    with pytest.raises(RateLimitedError) as exc:
        WhatsAppCloudApi._raise_for_status(resp)
    assert exc.value.retry_after == 42
    assert "rate limit hit" in str(exc.value)


def test_raise_for_status_maps_429_with_default_retry_after_when_header_absent():
    resp = _response(429, body={"error": {"message": "slow down"}})
    with pytest.raises(RateLimitedError) as exc:
        WhatsAppCloudApi._raise_for_status(resp)
    # Falls back to 1s when no Retry-After header is present.
    assert exc.value.retry_after == 1


def test_raise_for_status_maps_generic_non_2xx_to_cloud_api_error():
    resp = _response(400, body={"error": {"message": "bad recipient"}})
    with pytest.raises(WhatsAppCloudApiError) as exc:
        WhatsAppCloudApi._raise_for_status(resp)
    assert "400" in str(exc.value)
    assert "bad recipient" in str(exc.value)
    # The generic 400 is NOT a RateLimitedError (only 429 is).
    assert not isinstance(exc.value, RateLimitedError)


# ── send() driven through httpx.MockTransport (the only stub boundary) ────

pytestmark_async = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_send_posts_meta_messages_shape_and_returns_sendresult():
    captured: dict = {}

    def responder(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": _DIGITS, "wa_id": _DIGITS}],
                "messages": [{"id": "wamid.HBgABCDEF"}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    try:
        api = WhatsAppCloudApi(_config(), client=client)
        result = await api.send(OutboundMessage(to=_RAW_TO, text="hi"))
    finally:
        await client.aclose()

    # The request matches the Meta POST /messages endpoint shape.
    assert captured["method"] == "POST"
    assert captured["url"] == ("https://graph.facebook.com/v18.0/1234567890/messages")
    assert captured["headers"]["authorization"] == "Bearer EAAG-test-token"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["body"] == {
        "messaging_product": "whatsapp",
        "to": _DIGITS,
        "type": "text",
        "text": {"body": "hi"},
    }

    # SendResult carries the wamid + resolved wa_id from the envelope.
    assert isinstance(result, SendResult)
    assert result.wamid == "wamid.HBgABCDEF"
    assert result.wa_id == _DIGITS


@pytest.mark.asyncio
async def test_send_raises_rate_limited_on_429_response():
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "7"},
            json={"error": {"message": "too many requests"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    try:
        api = WhatsAppCloudApi(_config(), client=client)
        with pytest.raises(RateLimitedError) as exc:
            await api.send(OutboundMessage(to=_RAW_TO, text="hi"))
        assert exc.value.retry_after == 7
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_send_raises_cloud_api_error_on_generic_failure():
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "invalid token"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    try:
        api = WhatsAppCloudApi(_config(), client=client)
        with pytest.raises(WhatsAppCloudApiError) as exc:
            await api.send(OutboundMessage(to=_RAW_TO, text="hi"))
        assert not isinstance(exc.value, RateLimitedError)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_send_falls_back_to_request_to_when_wa_id_absent():
    def responder(request: httpx.Request) -> httpx.Response:
        # No contacts[].wa_id in the envelope.
        return httpx.Response(
            200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.X"}]}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    try:
        api = WhatsAppCloudApi(_config(), client=client)
        result = await api.send(OutboundMessage(to=_RAW_TO, text="hi"))
        # wa_id falls back to the invariant-normalized request `to`.
        assert result.wa_id == _DIGITS
        assert result.wamid == "wamid.X"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_send_raises_when_messages_id_missing_from_envelope():
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messaging_product": "whatsapp"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    try:
        api = WhatsAppCloudApi(_config(), client=client)
        with pytest.raises(WhatsAppCloudApiError, match="messages"):
            await api.send(OutboundMessage(to=_RAW_TO, text="hi"))
    finally:
        await client.aclose()
