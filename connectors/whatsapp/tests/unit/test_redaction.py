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
# P0-07: redact_phone takes the STARTUP-validated key as an explicit argument
# (no per-message os.environ read). The tests thread the key directly — the
# absent-key path (hmac_key=None) IS the runtime-soft sentinel half.
_KEY = "test-redaction-key-min-len"


def test_normalize_e164_strips_plus_and_separators():
    assert normalize_e164(_RAW) == _DIGITS
    assert normalize_e164("  +14155550100 ") == _DIGITS
    assert normalize_e164("14155550100") == _DIGITS


def test_normalize_e164_rejects_no_digit_input_without_leaking():
    with pytest.raises(ValueError) as exc:
        normalize_e164("not-a-number")
    # The raised message MUST NOT echo the raw input.
    assert "not-a-number" not in str(exc.value)


def test_redact_phone_returns_wa_prefixed_8hex_token():
    token = redact_phone("+14155550100", hmac_key=_KEY)
    assert token.startswith("wa:")
    hex_part = token[len("wa:") :]
    assert len(hex_part) == 8
    int(hex_part, 16)  # raises if not valid hex


def test_redact_phone_never_emits_raw_digits():
    token = redact_phone("+14155550100", hmac_key=_KEY)
    assert "14155550100" not in token
    assert "4155550100" not in token


def test_redact_phone_is_deterministic_and_key_stable():
    first = redact_phone("+14155550100", hmac_key=_KEY)
    second = redact_phone("+14155550100", hmac_key=_KEY)
    assert first == second
    # Surface-formatting variants of the same number normalize to one token.
    assert redact_phone("14155550100", hmac_key=_KEY) == first
    assert redact_phone("+1 (415) 555-0100", hmac_key=_KEY) == first


def test_redact_phone_different_key_yields_different_token():
    with_key_a = redact_phone("+14155550100", hmac_key="key-aaaaaaaaaaaaaaaaaa")
    with_key_b = redact_phone("+14155550100", hmac_key="key-bbbbbbbbbbbbbbbbbb")
    assert with_key_a != with_key_b


def test_redact_phone_missing_key_returns_sentinel_not_raw():
    # The runtime-soft half of the dual contract: an absent key (None) at the
    # per-message call site yields the sentinel — never the raw number.
    out = redact_phone("+14155550100", hmac_key=None)
    assert out == REDACTION_SENTINEL
    assert "14155550100" not in out


def test_redact_phone_empty_key_returns_sentinel_not_raw():
    # An empty-string key is treated identically to absent (transient glitch).
    out = redact_phone("+14155550100", hmac_key="")
    assert out == REDACTION_SENTINEL
    assert "14155550100" not in out


def test_redact_phone_unnormalizable_returns_sentinel_not_raw():
    out = redact_phone("no-digits-here", hmac_key=_KEY)
    assert out == REDACTION_SENTINEL
    assert "no-digits-here" not in out


def test_sentinel_is_distinct_from_any_success_token():
    token = redact_phone("+14155550100", hmac_key=_KEY)
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


def test_redact_phone_runtime_contract_preserved_sentinel_on_absent_key():
    """Invariant 2: runtime fail-soft contract holds.

    Even with the startup gate landed, :func:`redact_phone` MUST emit
    :data:`REDACTION_SENTINEL` when no key is threaded at call time (the
    transient-glitch path, now expressed as ``hmac_key=None`` rather than an
    unset env-var). This is the dual-contract guarantee: startup is loud,
    per-message is soft. A regression here would crash the connector on a
    single rotation glitch instead of degrading to a grep-able sentinel.
    """
    out = redact_phone("+14155550100", hmac_key=None)
    assert out == REDACTION_SENTINEL
    # And of course the raw number does NOT leak.
    assert "14155550100" not in out


# ---- P0-07 credential-blindness fix: the per-message path NEVER reads env ----


def test_redact_phone_ignores_os_environ_uses_threaded_key(monkeypatch):
    """The per-message path uses ONLY the threaded key, never os.environ.

    Set a DIFFERENT key in the environment than the one threaded in. If the
    function still read os.environ, the token would key off the env value;
    instead it keys off the threaded argument. This is the structural proof
    the per-message os.environ read at the former redaction.py:154 is GONE.
    """
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "env-key-DIFFERENT-from-threaded")
    via_threaded = redact_phone("+14155550100", hmac_key=_KEY)
    # The token keyed off the THREADED key, not the env key: it equals the
    # token computed with _KEY and differs from the token computed with the
    # env value.
    assert via_threaded == redact_phone("+14155550100", hmac_key=_KEY)
    assert via_threaded != redact_phone(
        "+14155550100", hmac_key="env-key-DIFFERENT-from-threaded"
    )


def test_redaction_config_redact_binds_startup_key():
    """RedactionConfig.redact() threads its own validated key into redact_phone."""
    config = RedactionConfig(hmac_key=_KEY)
    bound = config.redact("+14155550100")
    direct = redact_phone("+14155550100", hmac_key=_KEY)
    assert bound == direct
    assert bound.startswith("wa:")


def test_redaction_config_redact_with_empty_key_yields_sentinel():
    """A config holding an empty key redacts to the sentinel (fail-soft)."""
    config = RedactionConfig(hmac_key="")
    assert config.redact("+14155550100") == REDACTION_SENTINEL


def test_redaction_module_has_no_per_message_os_environ_read():
    """Structural: the per-message env read (former _hmac_key) is removed.

    ``_hmac_key`` was the helper that read os.environ on every redact_phone
    call (redaction.py:154). It is removed by P0-07; the only env read left is
    the startup gate ``RedactionConfig.from_env`` via ``_require_env``.
    """
    import delegate_connectors.whatsapp.redaction as redaction_mod

    assert not hasattr(redaction_mod, "_hmac_key")
