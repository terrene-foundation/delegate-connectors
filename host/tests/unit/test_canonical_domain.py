# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the producer-side canonical-domain reject gate.

``assert_canonical_signing_domain`` enforces the FROZEN
``specs/canonical-signing-bytes.md`` §1.2–§1.5 + §5 producer reject suite at the
host canonical-bytes boundary (the shared signing-byte helpers call it before
the frozen encoder). These tests pin both halves of the contract:

- ACCEPT: every canonical-JSON value the v1 wire form CAN carry passes silently
  (str, bool, in-range int incl. the ±(2^53-1) JS-safe boundary, None, nested
  mappings with string keys, lists, the spec §6 accept-vector payloads).
- REJECT: every §5 reject case raises ``NonConformantPayloadError`` — a float,
  NaN/Infinity, an integer at/over 2^53, a non-string object key, a lone
  surrogate — at every nesting level (top, nested dict value, list item).
"""

from __future__ import annotations

import pytest

from delegate_connectors_host.canonical_domain import (
    NonConformantPayloadError,
    assert_canonical_signing_domain,
)

_MAX_SAFE = 2**53 - 1  # 9007199254740991


# ── ACCEPT: conformant values pass silently ───────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"accepted": True, "to": "ops@x.com"},  # §6 Vector A payload
        {"count": 2, "message_ids": ["m1", "m2"]},  # §6 Vector C manifest
        {"n": 7, "unicode": "café"},  # §6 Vector B payload (non-ASCII raw UTF-8)
        {"max_safe": _MAX_SAFE, "min_safe": -_MAX_SAFE},  # §6 Vector E boundary
        {"nested": {"deep": {"ok": [1, 2, {"k": "v"}]}}},  # recursion
        {"none_is_ok": None, "bool_is_ok": False, "zero": 0},
        {"😀": "emoji", "�": "replacement"},  # §6 Vector D astral keys (valid strs)
    ],
)
def test_accepts_conformant_payloads(payload: dict) -> None:
    # Returns None (no raise) for every conformant payload.
    assert assert_canonical_signing_domain(payload) is None


def test_accepts_js_safe_integer_boundary_inclusive() -> None:
    # ±(2^53-1) is the inclusive JS-safe bound (§1.3) — MUST pass.
    assert_canonical_signing_domain({"v": _MAX_SAFE})
    assert_canonical_signing_domain({"v": -_MAX_SAFE})


# ── REJECT: §5 producer reject suite ──────────────────────────────────────────


def test_rejects_float() -> None:
    with pytest.raises(NonConformantPayloadError, match="float"):
        assert_canonical_signing_domain({"amount": 1.5})


def test_rejects_nan() -> None:
    with pytest.raises(NonConformantPayloadError, match="float"):
        assert_canonical_signing_domain({"x": float("nan")})


def test_rejects_infinity() -> None:
    with pytest.raises(NonConformantPayloadError, match="float"):
        assert_canonical_signing_domain({"x": float("inf")})
    with pytest.raises(NonConformantPayloadError, match="float"):
        assert_canonical_signing_domain({"x": float("-inf")})


def test_rejects_integer_at_2_pow_53() -> None:
    # 2^53 is the first JS-unsafe integer (§1.3) — MUST raise.
    with pytest.raises(NonConformantPayloadError, match="JS-safe domain"):
        assert_canonical_signing_domain({"v": 2**53})


def test_rejects_large_negative_integer() -> None:
    with pytest.raises(NonConformantPayloadError, match="JS-safe domain"):
        assert_canonical_signing_domain({"v": -(2**53)})


def test_rejects_non_string_key() -> None:
    with pytest.raises(NonConformantPayloadError, match="not a string"):
        assert_canonical_signing_domain({1: "a", 2: "b"})


def test_rejects_lone_surrogate() -> None:
    # "a\uD83Db" — a lone high surrogate; json.dumps would not raise, only
    # .encode("utf-8") does. The gate converts that into a typed, located reject.
    with pytest.raises(NonConformantPayloadError, match="lone surrogate"):
        assert_canonical_signing_domain({"k": "a\ud83db"})


def test_rejects_non_canonical_leaf_type() -> None:
    with pytest.raises(NonConformantPayloadError, match="not a canonical-JSON type"):
        assert_canonical_signing_domain({"k": {1, 2, 3}})  # set is not JSON


# ── REJECT propagates at every nesting level ──────────────────────────────────


def test_rejects_float_nested_in_dict_value() -> None:
    with pytest.raises(NonConformantPayloadError, match=r"\$\.outer\.inner"):
        assert_canonical_signing_domain({"outer": {"inner": 2.5}})


def test_rejects_float_nested_in_list_item() -> None:
    with pytest.raises(NonConformantPayloadError, match=r"\$\.items\[1\]"):
        assert_canonical_signing_domain({"items": [1, 3.5, 2]})


def test_rejects_non_string_key_in_nested_mapping() -> None:
    with pytest.raises(NonConformantPayloadError, match="not a string"):
        assert_canonical_signing_domain({"outer": {3: "bad"}})
