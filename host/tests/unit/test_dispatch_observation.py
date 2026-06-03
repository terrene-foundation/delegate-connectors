# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the host-observation seam (P0-08a).

The seam is the NET-NEW mechanism that closes the forge oracle architecture §2
verifies open today: the HOST invokes the brokered side effect, captures its own
observation, derives canonical receipt bytes from THAT host-captured return, and
REFUSES to derive bytes for any side effect it did not itself observe.

Contract under test
===================
1. The host invokes the brokered side effect through the ``BoundTransport``
   handle, and the canonical bytes derive ONLY from the host-captured return —
   the connector supplies the call args + a pure ``summarize`` projection, never
   the to-be-signed result.
2. The seam refuses (``UnobservedSideEffectError``) to derive bytes for a
   fabricated / foreign / wrong-kind ticket — including a connector double that
   returns a fabricated SUCCESS for a send the broker never performed.
3. The derived bytes are the §2 RECEIPT pre-image
   (``{action_id, observed_at, payload, signer_delegate_id}``), DISTINCT from the
   SDK audit-event slot (``{event_type, event_payload, signer_delegate_id}``).
4. With the host clock + receipt-id pinned, the derived bytes reproduce the
   FROZEN ``specs/canonical-signing-bytes.md`` §6 vectors byte-for-byte.
5. The seam composes AROUND the spine: its module makes ZERO direct ``kailash``
   imports (it reaches the frozen helpers only via the host's own
   ``signing_bytes`` module) — the "zero kailash spine edits" invariant.

P0-08a is observation only — signing (the Ed25519 key) is P0-08b, so the seam
produces bytes and refuses; it never signs.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from delegate_connectors_host.bound_transport import BoundTransport
from delegate_connectors_host.dispatch_observation import (
    DispatchObservationSeam,
    ObservedSideEffect,
    UnobservedSideEffectError,
)

# ── FROZEN spec §6 conformance vectors (specs/canonical-signing-bytes.md) ──────

_FIXED_CLOCK = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# Vector A — action, zero-µs. The payload is the host-captured SEND result,
# projected by summarize.
_VECTOR_A_ACTION_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_VECTOR_A_SIGNER = "11111111-1111-1111-1111-111111111111"
_VECTOR_A_PAYLOAD = {"accepted": True, "to": "ops@x.com"}
_VECTOR_A_BYTES = (
    b'{"action_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",'
    b'"observed_at":"2026-06-01T12:00:00.000000+00:00",'
    b'"payload":{"accepted":true,"to":"ops@x.com"},'
    b'"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}'
)

# Vector C — read receipt, zero-µs.
_VECTOR_C_READ_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_VECTOR_C_ATTESTER = "22222222-2222-2222-2222-222222222222"
_VECTOR_C_MANIFEST = {"count": 2, "message_ids": ["m1", "m2"]}
_VECTOR_C_BYTES = (
    b'{"attester_delegate_id":"22222222-2222-2222-2222-222222222222",'
    b'"manifest":{"count":2,"message_ids":["m1","m2"]},'
    b'"observed_at":"2026-06-01T12:00:00.000000+00:00",'
    b'"read_id":"cccccccc-cccc-cccc-cccc-cccccccccccc"}'
)


# ── transport doubles (real BoundTransport over async closures) ───────────────


def _transport(
    *, send_return: object = None, fetch_return: object = None
) -> tuple[BoundTransport, dict[str, object]]:
    """Build a BoundTransport whose send/fetch return fixed values + record calls.

    The recorder lets a test assert the HOST actually invoked the brokered handle
    (not the connector) and that ``summarize`` saw the host-captured return.
    """
    calls: dict[str, object] = {}

    async def broker_send(*args: object, **kwargs: object) -> object:
        calls["send_args"] = args
        calls["send_kwargs"] = kwargs
        calls["send_invoked"] = True
        return send_return

    async def broker_fetch(*args: object, **kwargs: object) -> object:
        calls["fetch_args"] = args
        calls["fetch_invoked"] = True
        return fetch_return

    return BoundTransport(send=broker_send, fetch=broker_fetch), calls


def _seam_pinned(receipt_id: str) -> DispatchObservationSeam:
    """A seam with the clock + receipt-id pinned to reproduce a spec vector."""
    return DispatchObservationSeam(
        clock=lambda: _FIXED_CLOCK,
        new_receipt_id=lambda: uuid.UUID(receipt_id),
    )


# ── 1. the host invokes + observes; bytes derive from the host-captured return ─


async def test_host_invokes_brokered_send_and_derives_from_captured_return():
    transport, calls = _transport(
        send_return={"accepted": True, "to": "ops@x.com", "smtp_extra": "ignored"}
    )
    seam = _seam_pinned(_VECTOR_A_ACTION_ID)

    seen: dict[str, object] = {}

    def summarize(result: object) -> dict[str, object]:
        seen["arg"] = result  # what did summarize receive?
        assert isinstance(result, dict)
        return {"accepted": result["accepted"], "to": result["to"]}

    observed = await seam.observe_action(
        transport, summarize, {"to": "ops@x.com"}, signer_delegate_id=_VECTOR_A_SIGNER
    )

    # The HOST invoked the brokered send (not the connector).
    assert calls["send_invoked"] is True
    assert calls["send_args"] == ({"to": "ops@x.com"},)
    # summarize was applied to the HOST-CAPTURED return, byte-for-byte.
    assert seen["arg"] == {"accepted": True, "to": "ops@x.com", "smtp_extra": "ignored"}
    # the ticket carries the raw captured value + the host-stamped identity
    assert observed.value == {
        "accepted": True,
        "to": "ops@x.com",
        "smtp_extra": "ignored",
    }
    assert observed.payload == _VECTOR_A_PAYLOAD
    assert observed.receipt_id == _VECTOR_A_ACTION_ID
    assert observed.observed_at == "2026-06-01T12:00:00.000000+00:00"

    # bytes derive ONLY from the host-observed return → match frozen Vector A
    assert seam.derive_action_bytes(observed) == _VECTOR_A_BYTES


async def test_host_invokes_brokered_fetch_and_derives_read_bytes():
    transport, calls = _transport(fetch_return=["m1", "m2"])
    seam = _seam_pinned(_VECTOR_C_READ_ID)

    def summarize(result: object) -> dict[str, object]:
        assert result == ["m1", "m2"]
        return {"count": len(result), "message_ids": list(result)}

    observed = await seam.observe_read(
        transport, summarize, attester_delegate_id=_VECTOR_C_ATTESTER
    )

    assert calls["fetch_invoked"] is True
    assert observed.value == ["m1", "m2"]
    assert observed.payload == _VECTOR_C_MANIFEST
    # bytes match frozen Vector C byte-for-byte
    assert seam.derive_read_bytes(observed) == _VECTOR_C_BYTES


# ── 2/3. refuse-on-unobserved: the forge closure ──────────────────────────────


def test_derive_refuses_fabricated_ticket_no_observation():
    """host.derive(arbitrary ticket) with no observed side effect -> refused."""
    seam = DispatchObservationSeam()
    # A ticket fabricated directly — NOT minted by observe_*; never invoked.
    fabricated = ObservedSideEffect(
        kind="action",
        payload={"accepted": True, "to": "victim@x.com"},
        value={"accepted": True},
        signer_delegate_id=_VECTOR_A_SIGNER,
        receipt_id=_VECTOR_A_ACTION_ID,
        observed_at="2026-06-01T12:00:00.000000+00:00",
    )
    with pytest.raises(UnobservedSideEffectError, match="did not observe"):
        seam.derive_action_bytes(fabricated)


async def test_derive_refuses_fabricated_success_for_send_broker_never_performed():
    """A connector double claiming SUCCESS for a send that never happened.

    The broker never performed the send (the host never called observe_action),
    so there is no host observation. The connector fabricates a success ticket
    and asks the host to derive bytes for it → the host produces NO bytes.
    """
    seam = DispatchObservationSeam()
    # The host did one genuine observation (a DIFFERENT, real send) so the seam's
    # ledger is non-empty — proving the refusal keys on THIS ticket's identity,
    # not on "the ledger is empty".
    real_transport, _ = _transport(send_return={"accepted": True, "to": "real@x.com"})
    await seam.observe_action(
        real_transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=_VECTOR_A_SIGNER,
    )

    fabricated = ObservedSideEffect(
        kind="action",
        payload={"accepted": True, "to": "ops@x.com"},  # a delivery that never happened
        value={"accepted": True},
        signer_delegate_id=_VECTOR_A_SIGNER,
        receipt_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        observed_at="2026-06-01T12:00:00.000000+00:00",
    )
    with pytest.raises(UnobservedSideEffectError):
        seam.derive_action_bytes(fabricated)


async def test_derive_refuses_copied_field_values_distinct_identity():
    """Copying a genuine ticket's FIELD VALUES into a new object is still refused.

    The capability is the ticket's object IDENTITY (eq=False), not any field a
    forger could read off and replicate. A reconstructed ticket with identical
    fields is a different object, absent from the ledger → refused.
    """
    transport, _ = _transport(send_return={"accepted": True, "to": "ops@x.com"})
    seam = _seam_pinned(_VECTOR_A_ACTION_ID)
    genuine = await seam.observe_action(
        transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=_VECTOR_A_SIGNER,
    )
    # genuine derives fine
    assert seam.derive_action_bytes(genuine) == _VECTOR_A_BYTES

    forged = ObservedSideEffect(
        kind=genuine.kind,
        payload=dict(genuine.payload),
        value=genuine.value,
        signer_delegate_id=genuine.signer_delegate_id,
        receipt_id=genuine.receipt_id,
        observed_at=genuine.observed_at,
    )
    assert forged != genuine  # identity equality: distinct objects
    with pytest.raises(UnobservedSideEffectError):
        seam.derive_action_bytes(forged)


async def test_derive_refuses_wrong_kind():
    """A read ticket handed to the write derive surface is refused (kind mismatch)."""
    transport, _ = _transport(fetch_return=["m1", "m2"])
    seam = _seam_pinned(_VECTOR_C_READ_ID)
    read_ticket = await seam.observe_read(
        transport,
        lambda r: {"count": len(r), "message_ids": list(r)},
        attester_delegate_id=_VECTOR_C_ATTESTER,
    )
    with pytest.raises(UnobservedSideEffectError, match="kind mismatch"):
        seam.derive_action_bytes(read_ticket)


async def test_derive_refuses_ticket_from_a_different_seam():
    """A ticket minted by seam A is refused by seam B (per-seam private ledger)."""
    transport, _ = _transport(send_return={"accepted": True, "to": "ops@x.com"})
    seam_a = _seam_pinned(_VECTOR_A_ACTION_ID)
    seam_b = DispatchObservationSeam()
    ticket = await seam_a.observe_action(
        transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=_VECTOR_A_SIGNER,
    )
    assert seam_a.derive_action_bytes(ticket) == _VECTOR_A_BYTES
    with pytest.raises(UnobservedSideEffectError):
        seam_b.derive_action_bytes(ticket)


def test_derive_refuses_non_ticket_object():
    """Passing a non-ObservedSideEffect (e.g. raw bytes) is refused, not crashed."""
    seam = DispatchObservationSeam()
    with pytest.raises(UnobservedSideEffectError):
        seam.derive_action_bytes(b"arbitrary bytes")  # type: ignore[arg-type]


# ── 4. receipt pre-image shape is DISTINCT from the audit-event slot ──────────


async def test_action_bytes_are_receipt_preimage_not_audit_event_shape():
    transport, _ = _transport(send_return={"accepted": True, "to": "ops@x.com"})
    seam = _seam_pinned(_VECTOR_A_ACTION_ID)
    observed = await seam.observe_action(
        transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=_VECTOR_A_SIGNER,
    )
    decoded = json.loads(seam.derive_action_bytes(observed))
    # §2.1 receipt pre-image shape
    assert sorted(decoded) == [
        "action_id",
        "observed_at",
        "payload",
        "signer_delegate_id",
    ]
    # NOT the SDK audit-event pre-image shape
    assert "event_type" not in decoded
    assert "event_payload" not in decoded


async def test_read_bytes_are_receipt_preimage_not_audit_event_shape():
    transport, _ = _transport(fetch_return=["m1", "m2"])
    seam = _seam_pinned(_VECTOR_C_READ_ID)
    observed = await seam.observe_read(
        transport,
        lambda r: {"count": len(r), "message_ids": list(r)},
        attester_delegate_id=_VECTOR_C_ATTESTER,
    )
    decoded = json.loads(seam.derive_read_bytes(observed))
    assert sorted(decoded) == [
        "attester_delegate_id",
        "manifest",
        "observed_at",
        "read_id",
    ]
    assert "event_type" not in decoded


# ── identity-binding: same payload, different observations → different bytes ──


async def test_two_observations_same_payload_distinct_bytes():
    """Two sends with identical payload produce DIFFERENT bytes (distinct id).

    The §2 pre-image binds the receipt identity (action_id), so a replayed
    payload is not byte-identical — the property the shared helpers exist for.
    """
    transport, _ = _transport(send_return={"accepted": True, "to": "ops@x.com"})
    seam = DispatchObservationSeam()  # real uuid4 → distinct action_ids
    summarize = lambda r: {"accepted": r["accepted"], "to": r["to"]}  # noqa: E731

    o1 = await seam.observe_action(
        transport, summarize, signer_delegate_id=_VECTOR_A_SIGNER
    )
    o2 = await seam.observe_action(
        transport, summarize, signer_delegate_id=_VECTOR_A_SIGNER
    )

    assert o1.receipt_id != o2.receipt_id
    assert seam.derive_action_bytes(o1) != seam.derive_action_bytes(o2)


# ── observation contract guards ────────────────────────────────────────────────


async def test_summarize_must_return_a_mapping():
    transport, _ = _transport(send_return="sent")
    seam = DispatchObservationSeam()
    with pytest.raises(TypeError, match="mapping"):
        await seam.observe_action(
            transport, lambda r: "not-a-mapping", signer_delegate_id=_VECTOR_A_SIGNER
        )


async def test_naive_clock_is_rejected_fixed_width_guard():
    transport, _ = _transport(send_return={"ok": True})
    seam = DispatchObservationSeam(
        clock=lambda: datetime(2026, 6, 1, 12, 0, 0)
    )  # naive
    with pytest.raises(ValueError, match="timezone-aware"):
        await seam.observe_action(
            transport, lambda r: {"ok": True}, signer_delegate_id=_VECTOR_A_SIGNER
        )


async def test_observed_at_is_fixed_width_microseconds_even_when_zero():
    transport, _ = _transport(send_return={"ok": True})
    seam = _seam_pinned(_VECTOR_A_ACTION_ID)
    observed = await seam.observe_action(
        transport, lambda r: {"ok": True}, signer_delegate_id=_VECTOR_A_SIGNER
    )
    # exactly 6 fractional digits + literal +00:00, never 'Z', never omit-when-zero
    assert observed.observed_at == "2026-06-01T12:00:00.000000+00:00"
    assert observed.observed_at.endswith("+00:00")
    assert ".000000+" in observed.observed_at


# ── brokered call that RAISES mints no ticket (runtime sibling of the forge) ──


async def test_brokered_send_failure_mints_no_ticket():
    """If the brokered send RAISES, the host mints no ticket and derives nothing.

    A send that raises (SMTP 550, timeout) is the runtime sibling of "a send that
    never happened": there is no observed success to sign. The exception MUST
    propagate before any ticket is minted — guarded explicitly so a future
    refactor that wrapped the await in try/except cannot silently re-open the forge.
    """

    async def boom(*a: object, **k: object) -> object:
        raise RuntimeError("SMTP 550 rejected")

    transport = BoundTransport(send=boom, fetch=boom)
    seam = DispatchObservationSeam()

    with pytest.raises(RuntimeError, match="SMTP 550"):
        await seam.observe_action(
            transport, lambda r: {"accepted": True}, signer_delegate_id=_VECTOR_A_SIGNER
        )
    # no ticket recorded
    assert len(seam._ledger) == 0


async def test_brokered_fetch_failure_mints_no_ticket():
    async def boom(*a: object, **k: object) -> object:
        raise RuntimeError("IMAP timeout")

    transport = BoundTransport(send=boom, fetch=boom)
    seam = DispatchObservationSeam()

    with pytest.raises(RuntimeError, match="IMAP timeout"):
        await seam.observe_read(
            transport, lambda r: {"count": 0}, attester_delegate_id=_VECTOR_C_ATTESTER
        )
    assert len(seam._ledger) == 0


# ── §5 reject suite propagates THROUGH the seam (producer-boundary smoke) ─────


async def test_non_conformant_summarize_output_refused_at_observation():
    """A summarize returning a §5-reject payload raises at observe (no bytes).

    The seam's producer boundary (build_*_signing_bytes -> assert_canonical_
    signing_domain) refuses a NaN/float/oversized-int/non-string-key payload
    BEFORE any ticket is minted — the host does not emit bytes that verify nowhere.
    """
    from delegate_connectors_host.canonical_domain import NonConformantPayloadError

    transport, _ = _transport(send_return={"raw": True})
    seam = DispatchObservationSeam()

    with pytest.raises(NonConformantPayloadError):
        await seam.observe_action(
            transport,
            lambda r: {"amount": float("nan")},
            signer_delegate_id=_VECTOR_A_SIGNER,
        )
    assert len(seam._ledger) == 0


async def test_seam_reproduces_frozen_vector_b_non_zero_microseconds():
    """Vector B (non-zero µs) through the seam locks _fixed_width's non-zero path.

    The seam GENERATES observed_at from its clock, so this is the only test that
    exercises fixed-width microsecond rendering on the .789012 branch end-to-end
    (the §3 footgun the retired 0.1.0 omit-when-zero form created).
    """
    vector_b_bytes = (
        b'{"action_id":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",'
        b'"observed_at":"2026-06-01T12:00:00.789012+00:00",'
        b'"payload":{"n":7,"unicode":"caf\xc3\xa9"},'  # 'café' raw UTF-8
        b'"signer_delegate_id":"11111111-1111-1111-1111-111111111111"}'
    )
    transport, _ = _transport(send_return={"n": 7, "unicode": "café"})
    seam = DispatchObservationSeam(
        clock=lambda: datetime(2026, 6, 1, 12, 0, 0, 789012, tzinfo=timezone.utc),
        new_receipt_id=lambda: uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )
    observed = await seam.observe_action(
        transport,
        lambda r: {"n": r["n"], "unicode": r["unicode"]},
        signer_delegate_id=_VECTOR_A_SIGNER,
    )
    assert observed.observed_at == "2026-06-01T12:00:00.789012+00:00"
    assert seam.derive_action_bytes(observed) == vector_b_bytes


async def test_seam_accepts_js_safe_integer_boundary():
    """±(2^53-1) flows through the seam's reject gate (boundary MUST pass)."""
    max_safe = 2**53 - 1
    transport, _ = _transport(send_return={"max_safe": max_safe})
    seam = _seam_pinned(_VECTOR_A_ACTION_ID)
    observed = await seam.observe_action(
        transport,
        lambda r: {"max_safe": r["max_safe"]},
        signer_delegate_id=_VECTOR_A_SIGNER,
    )
    assert str(max_safe).encode() in seam.derive_action_bytes(observed)


# ── reserved-kwarg shadowing is documented behavior (P008A-02) ────────────────


async def test_signer_delegate_id_is_reserved_not_forwarded_to_brokered_send():
    """`signer_delegate_id` is the host identity; it is NOT forwarded to send().

    Documented reserved-kwarg behavior: a brokered send never receives a
    `signer_delegate_id` kwarg (the seam consumes it). A future refactor changing
    this silently would fail this test.
    """
    transport, calls = _transport(send_return={"ok": True})
    seam = DispatchObservationSeam()
    await seam.observe_action(
        transport,
        lambda r: {"ok": True},
        {"to": "x@y.com"},
        signer_delegate_id=_VECTOR_A_SIGNER,
    )
    # send received the forwarded positional arg, but NOT signer_delegate_id
    assert calls["send_args"] == ({"to": "x@y.com"},)
    assert "signer_delegate_id" not in (calls.get("send_kwargs") or {})


# ── 5. zero kailash spine edits — the seam composes AROUND the spine ──────────


def test_seam_module_makes_zero_direct_kailash_imports():
    """The seam reaches the frozen helpers only via the host's own signing_bytes.

    "Zero kailash spine edits" (architecture §3.5 / repo-scope-discipline): the
    seam module MUST NOT import ``kailash`` directly — it composes around the SDK
    dispatch surface through the host package's own modules.
    """
    import delegate_connectors_host.dispatch_observation as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    import_lines = [
        ln.strip() for ln in source.splitlines() if re.match(r"^\s*(import|from)\s", ln)
    ]
    kailash_imports = [ln for ln in import_lines if re.search(r"\bkailash\b", ln)]
    assert (
        kailash_imports == []
    ), f"seam must not import kailash directly; found: {kailash_imports}"
