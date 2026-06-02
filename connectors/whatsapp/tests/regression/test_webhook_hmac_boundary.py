# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — binding security property 2: webhook HMAC boundary.

A payload with a wrong/tampered ``X-Hub-Signature-256`` MUST be REFUSED at the
ingest boundary: it never enters the in-process buffer and never emits the
``ingest.ok`` audit line (the verification IS the security boundary). The HMAC
compare is constant-time (``hmac.compare_digest``). A mismatched
``hub.verify_token`` yields NO ``hub.challenge`` echo.

Invariant 2: an HMAC-failed inbound never mutates the buffer and never emits an
audit event.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from delegate_connectors.whatsapp.redaction import RedactionConfig
from delegate_connectors.whatsapp.webhook import (
    WebhookConfig,
    WebhookIngest,
    verify_signature,
    verify_token_challenge,
)

pytestmark = pytest.mark.regression

_APP_SECRET = "test-app-secret-not-a-real-secret"
_VERIFY_TOKEN = "test-verify-token"
# P0-07: the ingest threads a STARTUP-validated PII-HMAC key into the inbound
# redaction path. Inject it explicitly so the test is self-contained (no
# os.environ dependency) and exercises the threaded-key path.
_REDACTION = RedactionConfig(hmac_key="test-pii-hmac-key-min-len")


def _config() -> WebhookConfig:
    return WebhookConfig(app_secret=_APP_SECRET, verify_token=_VERIFY_TOKEN)


def _ingest() -> WebhookIngest:
    return WebhookIngest(_config(), redaction_config=_REDACTION)


def _valid_payload() -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "14155550100",
                                        "type": "text",
                                        "text": {"body": "hi"},
                                        "timestamp": "1700000000",
                                        "id": "wamid.M1",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    ).encode("utf-8")


def _sign(raw_body: bytes, secret: str = _APP_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_tampered_signature_refused_buffer_untouched_no_audit(caplog):
    """A tampered signature: refused, buffer unchanged, no ingest.ok audit line."""
    ingest = _ingest()
    raw = _valid_payload()
    # A valid signature over a DIFFERENT body — i.e. the body was tampered after
    # signing (or the signature does not match these bytes).
    wrong_sig = _sign(raw + b"tampered")

    with caplog.at_level("INFO"):
        buffered = ingest.ingest(raw, wrong_sig)

    assert buffered == 0, "a body whose HMAC does not verify MUST buffer nothing"
    assert ingest.buffered_count == 0, "the buffer MUST NOT be mutated on refusal"
    # No audit event: the verified-ingest log line (ingest.ok) MUST be absent.
    messages = [r.message for r in caplog.records]
    assert "whatsapp.webhook.ingest.ok" not in messages
    # The refusal IS surfaced (without any payload bytes).
    assert "whatsapp.webhook.signature_invalid" in messages


def test_missing_signature_refused(caplog):
    """A None / absent signature header is refused — never reaches the buffer."""
    ingest = _ingest()
    raw = _valid_payload()

    with caplog.at_level("INFO"):
        assert ingest.ingest(raw, None) == 0
    assert ingest.buffered_count == 0
    assert "whatsapp.webhook.ingest.ok" not in [r.message for r in caplog.records]


def test_wrong_secret_signature_refused():
    """A signature computed under the WRONG app secret does not verify."""
    raw = _valid_payload()
    forged = _sign(raw, secret="attacker-guessed-secret")
    assert verify_signature(raw, forged, _config()) is False


def test_valid_signature_accepted_and_buffered(caplog):
    """A correctly-signed payload over the EXACT bytes verifies + buffers."""
    ingest = _ingest()
    raw = _valid_payload()
    good_sig = _sign(raw)

    with caplog.at_level("INFO"):
        buffered = ingest.ingest(raw, good_sig)

    assert buffered == 1
    assert ingest.buffered_count == 1
    # The verified-ingest audit line IS emitted for an accepted payload.
    assert "whatsapp.webhook.ingest.ok" in [r.message for r in caplog.records]


def test_verify_signature_compare_is_constant_time(monkeypatch):
    """The HMAC compare MUST route through hmac.compare_digest (constant-time).

    Behavioral proof: spy on hmac.compare_digest; verify_signature MUST call it
    for the final compare rather than a plain ``==`` (which leaks via timing).
    """
    raw = _valid_payload()
    good_sig = _sign(raw)

    calls: list[tuple] = []
    real_compare = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare(a, b)

    monkeypatch.setattr("delegate_connectors.whatsapp.webhook.hmac.compare_digest", spy)
    assert verify_signature(raw, good_sig, _config()) is True
    assert calls, "verify_signature MUST use hmac.compare_digest for the compare"


def test_verify_token_mismatch_yields_no_challenge_echo():
    """A mismatched hub.verify_token MUST NOT echo hub.challenge."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "attacker-guessed-token",
        "hub.challenge": "1234567890",
    }
    assert verify_token_challenge(params, _config()) is None


def test_verify_token_match_echoes_challenge():
    """The matching verify_token + subscribe mode DOES echo the challenge."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": _VERIFY_TOKEN,
        "hub.challenge": "1234567890",
    }
    assert verify_token_challenge(params, _config()) == "1234567890"


def test_verify_token_compare_is_constant_time(monkeypatch):
    """The verify-token compare MUST also route through hmac.compare_digest."""
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": _VERIFY_TOKEN,
        "hub.challenge": "1234567890",
    }
    calls: list[tuple] = []
    real_compare = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare(a, b)

    monkeypatch.setattr("delegate_connectors.whatsapp.webhook.hmac.compare_digest", spy)
    assert verify_token_challenge(params, _config()) == "1234567890"
    assert calls, "verify_token_challenge MUST use hmac.compare_digest"
