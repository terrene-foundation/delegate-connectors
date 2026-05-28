# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for phone-number PII redaction (the security floor)."""

from __future__ import annotations

import pytest

from delegate_connectors.whatsapp.redaction import (
    PII_HMAC_KEY_ENV,
    REDACTION_SENTINEL,
    normalize_e164,
    redact_phone,
)

# A representative E.164 and its bare-digit normalization, reused across tests.
_RAW = "+1 (415) 555-0100"
_DIGITS = "14155550100"


def test_normalize_e164_strips_plus_and_separators():
    assert normalize_e164(_RAW) == _DIGITS
    assert normalize_e164("  +14155550100 ") == _DIGITS
    assert normalize_e164("14155550100") == _DIGITS


def test_normalize_e164_rejects_no_digit_input_without_leaking():
    with pytest.raises(ValueError) as exc:
        normalize_e164("not-a-number")
    # The raised message MUST NOT echo the raw input.
    assert "not-a-number" not in str(exc.value)


def test_redact_phone_returns_wa_prefixed_8hex_token(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key-min-len")
    token = redact_phone("+14155550100")
    assert token.startswith("wa:")
    hex_part = token[len("wa:") :]
    assert len(hex_part) == 8
    int(hex_part, 16)  # raises if not valid hex


def test_redact_phone_never_emits_raw_digits(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key-min-len")
    token = redact_phone("+14155550100")
    assert "14155550100" not in token
    assert "4155550100" not in token


def test_redact_phone_is_deterministic_and_key_stable(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key-min-len")
    first = redact_phone("+14155550100")
    second = redact_phone("+14155550100")
    assert first == second
    # Surface-formatting variants of the same number normalize to one token.
    assert redact_phone("14155550100") == first
    assert redact_phone("+1 (415) 555-0100") == first


def test_redact_phone_different_key_yields_different_token(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "key-aaaaaaaaaaaaaaaaaa")
    with_key_a = redact_phone("+14155550100")
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "key-bbbbbbbbbbbbbbbbbb")
    with_key_b = redact_phone("+14155550100")
    assert with_key_a != with_key_b


def test_redact_phone_missing_key_returns_sentinel_not_raw(monkeypatch):
    monkeypatch.delenv(PII_HMAC_KEY_ENV, raising=False)
    out = redact_phone("+14155550100")
    assert out == REDACTION_SENTINEL
    assert "14155550100" not in out


def test_redact_phone_unnormalizable_returns_sentinel_not_raw(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key-min-len")
    out = redact_phone("no-digits-here")
    assert out == REDACTION_SENTINEL
    assert "no-digits-here" not in out


def test_sentinel_is_distinct_from_any_success_token(monkeypatch):
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key-min-len")
    token = redact_phone("+14155550100")
    assert token != REDACTION_SENTINEL
    assert not REDACTION_SENTINEL.startswith("wa:")
