# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Receipt-interop byte-stability gate (P0-05).

These vectors are transcribed VERBATIM from the FROZEN crypto core
``specs/canonical-signing-bytes.md`` §6 (protocol v1) — the byte-level
receipt-interop contract that the independent Rust ``dc-enterprise`` tier aligns
to (§11 + §6). They pin the exact canonical signing bytes the shared helpers
(`delegate_connectors_host.signing_bytes`) MUST produce, so a green BEHAVIORAL
conformance run cannot mask a byte-level break (spec §5 — two gates).

**Provenance (honest scope).** This is a byte-STABILITY + spec-conformance gate
against the Foundation spec's own frozen vectors. It is NOT a proven
cross-implementation interop run against a *running* Rust ``dc-enterprise``
build — that alignment is external / TRACK-ONLY (forest item F6). The claim this
gate substantiates is precisely: "the host helpers emit the frozen §6 canonical
bytes the Rust tier aligns to," no more.

The timestamp-form test guards the P0-05 migration directly: the retired
omit-when-zero `isoformat()` form (the yanked 0.1.0 connectors) is replaced by
fixed-width `isoformat(timespec="microseconds")` per §3.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from delegate_connectors_host.canonical_domain import NonConformantPayloadError
from delegate_connectors_host.signing_bytes import (
    build_action_signing_bytes,
    build_read_signing_bytes,
)

pytestmark = pytest.mark.conformance

_SIGNER = "11111111-1111-1111-1111-111111111111"
_ATTESTER = "22222222-2222-2222-2222-222222222222"

# --- §6 normative vectors: (inputs) -> expected canonical bytes (frozen) ---

VECTOR_A = (
    build_action_signing_bytes(
        {"accepted": True, "to": "ops@x.com"},
        signer_delegate_id=_SIGNER,
        action_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        observed_at="2026-06-01T12:00:00.000000+00:00",
    ),
    b'{"action_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","observed_at":"2026-06-01T12:00:00.000000+00:00","payload":{"accepted":true,"to":"ops@x.com"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}',
)

VECTOR_B = (
    build_action_signing_bytes(
        {"n": 7, "unicode": "café"},
        signer_delegate_id=_SIGNER,
        action_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        observed_at="2026-06-01T12:00:00.789012+00:00",
    ),
    '{"action_id":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","observed_at":"2026-06-01T12:00:00.789012+00:00","payload":{"n":7,"unicode":"café"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}'.encode(
        "utf-8"
    ),
)

VECTOR_C = (
    build_read_signing_bytes(
        {"count": 2, "message_ids": ["m1", "m2"]},
        attester_delegate_id=_ATTESTER,
        read_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        observed_at="2026-06-01T12:00:00.000000+00:00",
    ),
    b'{"attester_delegate_id":"22222222-2222-2222-2222-222222222222","manifest":{"count":2,"message_ids":["m1","m2"]},"observed_at":"2026-06-01T12:00:00.000000+00:00","read_id":"cccccccc-cccc-cccc-cccc-cccccccccccc"}',
)

# Vector D — code-point key order (NOT UTF-16): U+FFFD (65533) sorts before
# U+1F600 (128512); ensure_ascii=False emits raw UTF-8.
VECTOR_D = (
    build_action_signing_bytes(
        {"�": "replacement", "\U0001f600": "emoji"},
        signer_delegate_id=_SIGNER,
        action_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        observed_at="2026-06-01T12:00:00.000000+00:00",
    ),
    '{"action_id":"dddddddd-dddd-dddd-dddd-dddddddddddd","observed_at":"2026-06-01T12:00:00.000000+00:00","payload":{"�":"replacement","\U0001f600":"emoji"},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}'.encode(
        "utf-8"
    ),
)

# Vector E — JS-safe integer domain ±(2^53-1) (owner decision, journal/0002).
VECTOR_E = (
    build_action_signing_bytes(
        {"max_safe": 9007199254740991, "min_safe": -9007199254740991},
        signer_delegate_id=_SIGNER,
        action_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        observed_at="2026-06-01T12:00:00.000000+00:00",
    ),
    b'{"action_id":"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee","observed_at":"2026-06-01T12:00:00.000000+00:00","payload":{"max_safe":9007199254740991,"min_safe":-9007199254740991},"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}',
)


@pytest.mark.parametrize(
    "name,actual,expected",
    [
        ("A-action-zero-us", *VECTOR_A),
        ("B-action-unicode-us", *VECTOR_B),
        ("C-read-zero-us", *VECTOR_C),
        ("D-codepoint-key-order", *VECTOR_D),
        ("E-js-safe-int-domain", *VECTOR_E),
    ],
)
def test_canonical_bytes_match_frozen_spec_vectors(name, actual, expected):
    """Each helper emits the exact §6 frozen canonical bytes."""
    assert actual == expected, f"vector {name}: canonical bytes diverged from §6"


def test_observed_at_form_is_fixed_width_microseconds_even_when_zero():
    """§3: the retired omit-when-zero form is closed; zero µs → 6 digits, +00:00 not Z."""
    zero_us = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    s = zero_us.isoformat(timespec="microseconds")
    assert s == "2026-06-01T12:00:00.000000+00:00"
    assert s.endswith("+00:00") and not s.endswith("Z")
    # The bare (retired) form would have omitted the fractional part:
    assert zero_us.isoformat() == "2026-06-01T12:00:00+00:00"  # what we MUST NOT emit


def test_action_bytes_carry_fixed_width_microseconds_end_to_end():
    """A zero-µs observation flows through the sign helper as fixed-width µs."""
    observed_at = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat(
        timespec="microseconds"
    )
    out = build_action_signing_bytes(
        {"ok": True},
        signer_delegate_id=_SIGNER,
        action_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        observed_at=observed_at,
    )
    assert b'"observed_at":"2026-06-01T12:00:00.000000+00:00"' in out


# --- §5 reject suite: the SECOND conformance gate (producer MUST raise) --------
#
# spec §5: "An implementation claiming interoperability MUST pass BOTH [accept]
# gates ... Plus the reject suite — the canonicalizer/verifier MUST reject (raise,
# never sign/accept): a float; a NaN/Infinity; an integer outside [-(2^53-1),
# 2^53-1]; a non-string object key; a string with a lone surrogate ..."
# The §6 reject cases assert REJECTION (no bytes). These exercise the producer
# (signer) half through the shared signing-byte helpers — the boundary §1.4 names.

_REJECT_PAYLOADS = {
    "float-1.5": {"v": 1.5},
    "nan": {"v": float("nan")},
    "infinity": {"v": float("inf")},
    "neg-infinity": {"v": float("-inf")},
    "int-2pow53-first-js-unsafe": {"v": 2**53},  # 9007199254740992
    "int-2pow64": {"v": 2**64},
    "non-string-key": {1: "a"},
    "lone-surrogate": {"k": "a\ud83db"},
}


@pytest.mark.parametrize("name", sorted(_REJECT_PAYLOADS))
def test_action_signing_rejects_spec_reject_suite(name):
    """§5 reject suite — the action signer MUST raise, never emit signable bytes."""
    with pytest.raises(NonConformantPayloadError):
        build_action_signing_bytes(
            _REJECT_PAYLOADS[name],
            signer_delegate_id=_SIGNER,
            action_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
            observed_at="2026-06-01T12:00:00.000000+00:00",
        )


@pytest.mark.parametrize("name", sorted(_REJECT_PAYLOADS))
def test_read_signing_rejects_spec_reject_suite(name):
    """§5 reject suite — the read attester MUST raise, never emit signable bytes."""
    with pytest.raises(NonConformantPayloadError):
        build_read_signing_bytes(
            _REJECT_PAYLOADS[name],
            attester_delegate_id=_ATTESTER,
            read_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            observed_at="2026-06-01T12:00:00.000000+00:00",
        )
