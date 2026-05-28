# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the webhook ingest protocol (the security boundary).

These exercise the HMAC verification boundary, the verify-token handshake, the
envelope parse + sender redaction, and the one-shot buffer drain — all stdlib,
no HTTP server, no httpx.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from delegate_connectors.whatsapp.redaction import PII_HMAC_KEY_ENV
from delegate_connectors.whatsapp.webhook import (
    InboundMessage,
    WebhookConfig,
    WebhookIngest,
    parse_inbound_envelope,
    verify_signature,
    verify_token_challenge,
)

_APP_SECRET = "test-app-secret-value"
_VERIFY_TOKEN = "test-verify-token"
_RAW_SENDER = "14155550100"


def _config() -> WebhookConfig:
    return WebhookConfig(app_secret=_APP_SECRET, verify_token=_VERIFY_TOKEN)


def _sign(raw_body: bytes, secret: str = _APP_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _inbound_payload(sender: str = _RAW_SENDER, text: str = "hello") -> bytes:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": sender,
                                    "id": "wamid.TEST",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode("utf-8")


# --- verify-token handshake -------------------------------------------------


def test_handshake_echoes_challenge_on_matching_verify_token():
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": _VERIFY_TOKEN,
        "hub.challenge": "CHALLENGE-123",
    }
    assert verify_token_challenge(params, _config()) == "CHALLENGE-123"


def test_handshake_rejects_on_verify_token_mismatch():
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong-token",
        "hub.challenge": "CHALLENGE-123",
    }
    assert verify_token_challenge(params, _config()) is None


def test_handshake_rejects_on_wrong_mode():
    params = {
        "hub.mode": "unsubscribe",
        "hub.verify_token": _VERIFY_TOKEN,
        "hub.challenge": "CHALLENGE-123",
    }
    assert verify_token_challenge(params, _config()) is None


# --- HMAC signature boundary ------------------------------------------------


def test_verify_signature_accepts_valid_signature():
    body = _inbound_payload()
    assert verify_signature(body, _sign(body), _config()) is True


def test_verify_signature_refuses_tampered_body():
    body = _inbound_payload()
    sig = _sign(body)
    tampered = body + b" "  # one byte appended -> signature no longer matches
    assert verify_signature(tampered, sig, _config()) is False


def test_verify_signature_refuses_wrong_secret():
    body = _inbound_payload()
    sig = _sign(body, secret="attacker-secret")
    assert verify_signature(body, sig, _config()) is False


def test_verify_signature_refuses_missing_or_malformed_header():
    body = _inbound_payload()
    assert verify_signature(body, None, _config()) is False
    assert verify_signature(body, "", _config()) is False
    assert verify_signature(body, "md5=deadbeef", _config()) is False


# --- ingest: verify-then-buffer ---------------------------------------------


def test_valid_signed_payload_is_buffered_and_drains(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    ingest = WebhookIngest(_config())
    body = _inbound_payload(text="hi there")
    n = ingest.ingest(body, _sign(body))
    assert n == 1
    assert ingest.buffered_count == 1

    drained = ingest.drain_one()
    assert isinstance(drained, InboundMessage)
    assert drained.text == "hi there"
    assert drained.message_type == "text"
    # The one-shot drain empties the buffer.
    assert ingest.buffered_count == 0
    assert ingest.drain_one() is None


def test_buffered_record_redacts_sender_no_raw_number(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    ingest = WebhookIngest(_config())
    body = _inbound_payload(sender=_RAW_SENDER)
    ingest.ingest(body, _sign(body))
    msg = ingest.drain_one()
    assert msg is not None
    assert msg.sender_redacted.startswith("wa:")
    # The raw number MUST be absent from the redacted token.
    assert _RAW_SENDER not in msg.sender_redacted


def test_tampered_signature_is_refused_and_never_buffered(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    ingest = WebhookIngest(_config())
    body = _inbound_payload()
    tampered_sig = _sign(body + b"tamper")  # signature over different bytes
    n = ingest.ingest(body, tampered_sig)
    assert n == 0
    assert ingest.buffered_count == 0  # nothing entered the audit/buffer path
    assert ingest.drain_one() is None


def test_missing_signature_is_refused_and_never_buffered(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    ingest = WebhookIngest(_config())
    body = _inbound_payload()
    assert ingest.ingest(body, None) == 0
    assert ingest.buffered_count == 0


def test_verified_inbound_feeds_window_sink(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    recorded: list[tuple[str, str]] = []
    ingest = WebhookIngest(
        _config(), window_sink=lambda phone, ts: recorded.append((phone, ts))
    )
    body = _inbound_payload(sender="14155550100")
    ingest.ingest(body, _sign(body))
    assert recorded == [("14155550100", "1700000000")]


def test_tampered_payload_does_not_feed_window_sink(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    recorded: list[tuple[str, str]] = []
    ingest = WebhookIngest(
        _config(), window_sink=lambda phone, ts: recorded.append((phone, ts))
    )
    body = _inbound_payload()
    ingest.ingest(body, _sign(body + b"x"))  # bad signature
    assert recorded == []  # refused payloads never reach the window tracker


# --- envelope parse ---------------------------------------------------------


def test_parse_envelope_redacts_and_extracts_text(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    payload = json.loads(_inbound_payload(text="parsed body").decode())
    messages = parse_inbound_envelope(payload)
    assert len(messages) == 1
    msg = messages[0]
    assert msg.text == "parsed body"
    assert msg.sender_redacted.startswith("wa:")
    assert _RAW_SENDER not in msg.sender_redacted
    assert msg.sender_e164_normalized == _RAW_SENDER


def test_parse_envelope_ignores_statuses_only_payload(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key")
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]}
    assert parse_inbound_envelope(payload) == []
