# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the host-side Ed25519 signer (P0-08b).

The signer is the SECOND forge-closure mechanism: the host holds the Ed25519 key
and signs ONLY the canonical bytes the P0-08a seam derived from a host-observed
side effect. The connector holds neither the key nor a signer thunk.

Contract under test
===================
- A receipt the host signs over a host-OBSERVED side effect VERIFIES under the
  SDK ``Ed25519Verifier`` (raw-64-byte signature, microsecond ``observed_at``)
  — both the write (``SignedActionEnvelope``) and read (``AttestedReadReceipt``)
  paths, through the host's own ``verify_action_envelope`` / ``verify_read_receipt``.
- The host signs EXACTLY the seam-derived bytes (no re-derivation, no drift).
- There is NO path to sign bytes the host did not observe: ``sign_action`` /
  ``attest_read`` route through the seam's refuse-on-unobserved gate, so a
  fabricated / foreign-seam / wrong-kind ticket raises ``UnobservedSideEffectError``
  and produces NO signature. ``HostSigner`` exposes no ``sign(bytes)`` surface and
  no signing-key accessor.

P0-08b builds + tests the signer as a transitional orphan — wiring the reference
connectors onto it (so the connector loses its raw key) is P0-09 / P0-11.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate.types import DelegateIdentity, PrincipalDirectory
from kailash.delegate.verifier import Ed25519Verifier

from delegate_connectors_host.bound_transport import BoundTransport
from delegate_connectors_host.dispatch_observation import (
    DispatchObservationSeam,
    ObservedSideEffect,
    UnobservedSideEffectError,
)
from delegate_connectors_host.dispatch_signing import HostSigner
from delegate_connectors_host.signing_bytes import (
    verify_action_envelope,
    verify_read_receipt,
)


# ── fixtures: a host key registered in the verifier's directory ───────────────


def _verifier_for(
    delegate_id: uuid.UUID, signing_key: Ed25519PrivateKey
) -> Ed25519Verifier:
    """An Ed25519Verifier whose directory maps ``delegate_id`` -> the host pubkey.

    The host signs with ``signing_key``; the receipt's ``signer_delegate_id`` is
    ``str(delegate_id)``; verification resolves that id to the registered raw
    32-byte public key. This mirrors exactly how the connectors register today.
    """
    pk = signing_key.public_key().public_bytes_raw()
    identity = DelegateIdentity(
        delegate_id=delegate_id,
        sovereign_ref="sovereign-1",
        role_binding_ref="rb-1",
        genesis_ref="g-1",
    )
    directory = PrincipalDirectory(
        identities=(identity,), verification_keys={delegate_id: pk}
    )
    return Ed25519Verifier(directory)


def _transport(*, send_return=None, fetch_return=None) -> BoundTransport:
    async def send(*a, **k):
        return send_return

    async def fetch(*a, **k):
        return fetch_return

    return BoundTransport(send=send, fetch=fetch)


def _setup():
    """A host key + delegate id + verifier + a fresh seam + signer."""
    sk = Ed25519PrivateKey.generate()
    delegate_id = uuid.uuid4()
    verifier = _verifier_for(delegate_id, sk)
    seam = DispatchObservationSeam()
    signer = HostSigner(seam, sk)
    return sk, delegate_id, verifier, seam, signer


# ── positive: host-signed receipts verify under the SDK verifier ──────────────


async def test_signed_action_verifies_under_sdk_verifier():
    sk, delegate_id, verifier, seam, signer = _setup()
    transport = _transport(send_return={"accepted": True, "to": "ops@x.com"})

    observed = await seam.observe_action(
        transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=str(delegate_id),
    )
    envelope = signer.sign_action(observed)

    # raw-64-byte Ed25519 signature (spec §4)
    assert isinstance(envelope.signature, bytes) and len(envelope.signature) == 64
    assert envelope.action_id == uuid.UUID(observed.receipt_id)
    assert envelope.signer_delegate_id == str(delegate_id)
    # the host signed EXACTLY the seam-derived bytes (no drift)
    assert envelope.canonical_bytes == seam.derive_action_bytes(observed)
    # verifies under the SDK Ed25519Verifier (observed_at committed in the bytes)
    assert (
        verify_action_envelope(envelope, verifier, observed_at=observed.observed_at)
        is True
    )


async def test_attested_read_verifies_under_sdk_verifier():
    sk, delegate_id, verifier, seam, signer = _setup()
    transport = _transport(fetch_return=["m1", "m2"])

    observed = await seam.observe_read(
        transport,
        lambda r: {"count": len(r), "message_ids": list(r)},
        attester_delegate_id=str(delegate_id),
    )
    value, receipt = signer.attest_read(observed)

    assert value == ["m1", "m2"]  # host-captured fetched value returned
    assert isinstance(receipt.attestation, bytes) and len(receipt.attestation) == 64
    assert receipt.read_id == uuid.UUID(observed.receipt_id)
    # observed_at reconstructed as a tz-aware datetime that round-trips to the
    # exact fixed-width string committed in the signed bytes (§3 / P0-05)
    assert receipt.observed_at.tzinfo is not None
    assert (
        receipt.observed_at.isoformat(timespec="microseconds") == observed.observed_at
    )
    assert receipt.canonical_bytes == seam.derive_read_bytes(observed)
    assert verify_read_receipt(receipt, dict(observed.payload), verifier) is True


async def test_signed_action_fails_verification_under_a_foreign_verifier():
    """A receipt signed by the host key does NOT verify under an unrelated key."""
    sk, delegate_id, verifier, seam, signer = _setup()
    transport = _transport(send_return={"accepted": True, "to": "ops@x.com"})
    observed = await seam.observe_action(
        transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=str(delegate_id),
    )
    envelope = signer.sign_action(observed)

    # a verifier holding a DIFFERENT key for the same delegate_id
    foreign_verifier = _verifier_for(delegate_id, Ed25519PrivateKey.generate())
    assert (
        verify_action_envelope(
            envelope, foreign_verifier, observed_at=observed.observed_at
        )
        is False
    )


# ── negative: no path to sign bytes the host did not observe (forge closure) ──


def test_sign_action_refuses_fabricated_ticket():
    sk, delegate_id, verifier, seam, signer = _setup()
    fabricated = ObservedSideEffect(
        kind="action",
        payload={"accepted": True, "to": "victim@x.com"},
        value=None,
        signer_delegate_id=str(delegate_id),
        receipt_id=str(uuid.uuid4()),
        observed_at="2026-06-01T12:00:00.000000+00:00",
    )
    with pytest.raises(UnobservedSideEffectError):
        signer.sign_action(fabricated)


async def test_attest_read_refuses_action_ticket_wrong_kind():
    sk, delegate_id, verifier, seam, signer = _setup()
    transport = _transport(send_return={"accepted": True})
    action_ticket = await seam.observe_action(
        transport, lambda r: {"accepted": True}, signer_delegate_id=str(delegate_id)
    )
    with pytest.raises(UnobservedSideEffectError):
        signer.attest_read(action_ticket)


async def test_sign_action_refuses_read_ticket_wrong_kind():
    sk, delegate_id, verifier, seam, signer = _setup()
    transport = _transport(fetch_return=["m1"])
    read_ticket = await seam.observe_read(
        transport, lambda r: {"count": len(r)}, attester_delegate_id=str(delegate_id)
    )
    with pytest.raises(UnobservedSideEffectError):
        signer.sign_action(read_ticket)


async def test_signer_refuses_ticket_from_a_different_seam():
    sk, delegate_id, verifier, seam, signer = _setup()
    other_seam = DispatchObservationSeam()
    transport = _transport(send_return={"accepted": True})
    # observed by ANOTHER seam, not the one the signer is bound to
    foreign = await other_seam.observe_action(
        transport, lambda r: {"accepted": True}, signer_delegate_id=str(delegate_id)
    )
    with pytest.raises(UnobservedSideEffectError):
        signer.sign_action(foreign)


# ── structural: connector holds neither key nor a sign-arbitrary-bytes thunk ──


def test_host_signer_exposes_no_sign_arbitrary_bytes_surface():
    """No public method signs caller-supplied bytes; the only inputs are tickets."""
    public = {m for m in dir(HostSigner) if not m.startswith("_")}
    assert public == {
        "sign_action",
        "attest_read",
    }, f"HostSigner must expose ONLY ticket-routed signing; got extra: {public}"


def test_host_signer_key_is_private_no_accessor():
    """The signing key is held private (slots, no public accessor)."""
    sk, delegate_id, verifier, seam, signer = _setup()
    # no instance __dict__ (slots), and no public attribute returns the key
    assert not hasattr(signer, "__dict__")
    assert not hasattr(signer, "signing_key")
    assert not hasattr(signer, "key")


def test_host_signer_rejects_non_key_and_non_seam():
    sk, delegate_id, verifier, seam, signer = _setup()
    with pytest.raises(TypeError, match="Ed25519PrivateKey"):
        HostSigner(seam, object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="DispatchObservationSeam"):
        HostSigner(object(), sk)  # type: ignore[arg-type]


# ── identity binding: same payload, distinct receipts → distinct signatures ──


async def test_two_signed_actions_same_payload_distinct_signatures():
    sk, delegate_id, verifier, seam, signer = _setup()
    transport = _transport(send_return={"accepted": True, "to": "ops@x.com"})
    summarize = lambda r: {"accepted": r["accepted"], "to": r["to"]}  # noqa: E731

    o1 = await seam.observe_action(
        transport, summarize, signer_delegate_id=str(delegate_id)
    )
    o2 = await seam.observe_action(
        transport, summarize, signer_delegate_id=str(delegate_id)
    )
    e1, e2 = signer.sign_action(o1), signer.sign_action(o2)

    # distinct action_id bound into the signed bytes → distinct signatures
    assert e1.action_id != e2.action_id
    assert e1.signature != e2.signature
    # both still verify
    assert verify_action_envelope(e1, verifier, observed_at=o1.observed_at) is True
    assert verify_action_envelope(e2, verifier, observed_at=o2.observed_at) is True


# ── observed_at round-trip at the zero-microsecond boundary (retired footgun) ─


async def test_attest_read_zero_microsecond_observed_at_round_trips():
    """The sharpest reconstruction edge: a whole-second (zero-µs) observation.

    The retired 0.1.0 omit-when-zero `isoformat()` form is the §3 footgun; this
    locks that the signer's datetime reconstruction round-trips byte-identically
    at zero microseconds AND the receipt still verifies under the SDK verifier.
    """
    sk = Ed25519PrivateKey.generate()
    delegate_id = uuid.uuid4()
    verifier = _verifier_for(delegate_id, sk)
    seam = DispatchObservationSeam(
        clock=lambda: datetime(2026, 6, 3, 9, 0, 0, tzinfo=timezone.utc)  # zero µs
    )
    signer = HostSigner(seam, sk)
    transport = _transport(fetch_return=["m1"])

    observed = await seam.observe_read(
        transport, lambda r: {"count": len(r)}, attester_delegate_id=str(delegate_id)
    )
    assert (
        observed.observed_at == "2026-06-03T09:00:00.000000+00:00"
    )  # fixed-width, 6 digits
    value, receipt = signer.attest_read(observed)
    # reconstructed datetime re-renders the EXACT signed string (lossless)
    assert (
        receipt.observed_at.isoformat(timespec="microseconds") == observed.observed_at
    )
    assert verify_read_receipt(receipt, dict(observed.payload), verifier) is True


async def test_signed_envelope_payload_isolated_from_ticket():
    """Mutating the envelope's payload does not leak back into the observation.

    `sign_action` defensively copies `dict(observed.payload)`; this regression
    guards a future refactor from dropping that copy and aliasing the ticket.
    """
    sk, delegate_id, verifier, seam, signer = _setup()
    transport = _transport(send_return={"accepted": True, "to": "ops@x.com"})
    observed = await seam.observe_action(
        transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=str(delegate_id),
    )
    envelope = signer.sign_action(observed)
    envelope.payload["accepted"] = False  # mutate the envelope's payload dict
    assert observed.payload["accepted"] is True  # ticket payload unaffected
