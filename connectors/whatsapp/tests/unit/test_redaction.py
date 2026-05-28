# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for phone-number PII redaction (the security floor)."""

from __future__ import annotations

import pytest

from delegate_connectors.whatsapp.redaction import (
    PII_HMAC_KEY_ENV,
    REDACTION_SENTINEL,
    RedactionConfig,
    RedactionConfigError,
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


# ---- L2 security fix — RedactionConfig.from_env() startup gate (todo 15) -----
# Two invariants (mirroring the module docstring's DUAL CONTRACT):
#   1. RedactionConfig.from_env() raises RedactionConfigError when
#      WHATSAPP_PII_HMAC_KEY is unset OR empty (loud at startup).
#   2. redact_phone() keeps emitting the sentinel on per-message redaction
#      failure (runtime robustness preserved across rotation glitches).


def test_redaction_config_from_env_raises_when_key_unset(monkeypatch):
    """Invariant 1: startup gate refuses when the env-var is absent."""
    monkeypatch.delenv(PII_HMAC_KEY_ENV, raising=False)
    with pytest.raises(RedactionConfigError) as exc:
        RedactionConfig.from_env()
    # Error message names the var so operators can act on it.
    assert PII_HMAC_KEY_ENV in str(exc.value)


def test_redaction_config_from_env_raises_when_key_empty(monkeypatch):
    """Invariant 1: empty-string env-var is treated as unset."""
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "")
    with pytest.raises(RedactionConfigError) as exc:
        RedactionConfig.from_env()
    assert PII_HMAC_KEY_ENV in str(exc.value)


def test_redaction_config_from_env_succeeds_with_valid_key(monkeypatch):
    """Invariant 1 positive: a valid key produces a usable config object."""
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-redaction-key-min-len")
    config = RedactionConfig.from_env()
    assert config.hmac_key == "test-redaction-key-min-len"


def test_redaction_config_error_subclasses_value_error():
    """Subclasses ValueError so generic config-load handlers still see it."""
    assert issubclass(RedactionConfigError, ValueError)


def test_redact_phone_runtime_contract_preserved_sentinel_on_unset_key(monkeypatch):
    """Invariant 2: runtime fail-soft contract holds.

    Even with the startup gate landed, :func:`redact_phone` MUST continue to
    emit :data:`REDACTION_SENTINEL` when the env-var is unset at call time.
    This is the dual-contract guarantee: startup is loud, per-message is
    soft. A regression here would crash the connector on a single rotation
    glitch instead of degrading to a grep-able sentinel in the audit trail.
    """
    monkeypatch.delenv(PII_HMAC_KEY_ENV, raising=False)
    out = redact_phone("+14155550100")
    assert out == REDACTION_SENTINEL
    # And of course the raw number does NOT leak.
    assert "14155550100" not in out
