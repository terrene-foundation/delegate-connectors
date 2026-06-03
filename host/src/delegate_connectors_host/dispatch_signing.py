# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""The host-side Ed25519 signer over the P0-08a observation seam (Phase-0, P0-08b).

This is the SECOND of the three composed mechanisms that close the forge oracle
(P0-08a host-observation seam · **P0-08b host-side signer** · P0-09/P0-11
connector loses action-invocation ownership). Today the connector holds the raw
Ed25519 signing key (`connector.py:160`) and signs in `_sign` (`connector.py:184`)
— and architecture §3.5 layer 2(b) names handing the connector a signer thunk a
**forge oracle**. P0-08b relocates the key host-side.

The structural closure: :class:`HostSigner` exposes ONLY
:meth:`sign_action` / :meth:`attest_read`, both of which take an
:class:`~delegate_connectors_host.dispatch_observation.ObservedSideEffect` ticket
and route through the seam's ``derive_*_bytes`` gate — which REFUSES any side
effect the host did not itself observe. There is **no** ``sign(bytes)`` surface:
the host cannot be asked to sign arbitrary bytes, only the canonical bytes the
P0-08a seam derived from the host-observed brokered side effect. The signing key
is private (``__slots__``, no accessor); the connector holds neither the key nor
a signer thunk.

What this seam does NOT do (later shards)
=========================================
- **Wiring** the reference connectors onto the host signer (so the connector at
  `connector.py:160`/`:184` loses the key) is **P0-09 / P0-11 (Wave 7)**. Like
  the broker (P0-07) and the observation seam (P0-08a), this shard BUILDS + TESTS
  the signer but has no production call site yet — a transitional orphan accepted
  per the Phase-0 plan.

Wire form
=========
Signatures are RAW 64-byte Ed25519 detached signatures
(``Ed25519PrivateKey.sign``) per ``specs/canonical-signing-bytes.md`` §4 — the
exact wire form the SDK :class:`~kailash.delegate.verifier.Ed25519Verifier`
checks and the connectors' current ``_sign`` produces. Produced envelopes /
receipts verify under that verifier (binding via the directory the verifier
consults). ZERO kailash spine edits: this module composes around the SDK dispatch
types, constructing them from host-observed state.

See ``workspaces/connector-platform/02-plans/01-architecture.md`` §3.5 layer 2.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from kailash.delegate.dispatch import AttestedReadReceipt, SignedActionEnvelope

from delegate_connectors_host.dispatch_observation import (
    DispatchObservationSeam,
    ObservedSideEffect,
)

__all__ = ["HostSigner"]


class HostSigner:
    """Host-held Ed25519 signer that signs ONLY P0-08a-observed side effects.

    The host owns the signing key; the connector holds neither the key nor a
    signer thunk. Both signing surfaces take an :class:`ObservedSideEffect` minted
    by the bound seam and route through the seam's refuse-on-unobserved derive
    gate, so there is no path to sign bytes the host did not itself observe.

    Parameters
    ----------
    seam:
        The :class:`DispatchObservationSeam` whose observations this signer signs.
        ``sign_action`` / ``attest_read`` derive their bytes through THIS seam, so
        a ticket from a different seam (or a fabricated ticket) is refused.
    signing_key:
        The host-held Ed25519 private key. Stored private (``__slots__``, no
        accessor); the only thing reachable through this object is a signature
        over seam-derived bytes.
    """

    __slots__ = ("_seam", "_signing_key")

    def __init__(
        self,
        seam: DispatchObservationSeam,
        signing_key: Ed25519PrivateKey,
    ) -> None:
        if not isinstance(seam, DispatchObservationSeam):
            raise TypeError(
                f"seam MUST be a DispatchObservationSeam; got {type(seam).__name__}"
            )
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise TypeError(
                "signing_key MUST be an Ed25519PrivateKey (the host holds the key, "
                f"not the connector); got {type(signing_key).__name__}"
            )
        self._seam = seam
        self._signing_key = signing_key

    def sign_action(self, observed: ObservedSideEffect) -> SignedActionEnvelope:
        """Sign a host-observed WRITE; return a verifiable :class:`SignedActionEnvelope`.

        Derives the canonical bytes through the seam (refuses an unobserved /
        fabricated / foreign-seam / read-kind ticket via
        :class:`~delegate_connectors_host.dispatch_observation.UnobservedSideEffectError`),
        signs them with the host key (raw 64-byte Ed25519), and constructs the
        envelope from the host-observed state. The signed timestamp is committed
        inside ``canonical_bytes`` (the runtime envelope has no ``observed_at``
        field); verify with ``verify_action_envelope(env, verifier,
        observed_at=observed.observed_at)``.
        """
        canonical_bytes = self._seam.derive_action_bytes(observed)
        signature = self._signing_key.sign(canonical_bytes)
        return SignedActionEnvelope(
            action_id=uuid.UUID(observed.receipt_id),
            canonical_bytes=canonical_bytes,
            signature=signature,
            signer_delegate_id=observed.signer_delegate_id,
            payload=dict(observed.payload),
        )

    def attest_read(
        self, observed: ObservedSideEffect
    ) -> tuple[Any, AttestedReadReceipt]:
        """Attest a host-observed READ; return ``(value, AttestedReadReceipt)``.

        Derives the canonical bytes through the seam (refuses an unobserved /
        fabricated / foreign-seam / action-kind ticket), signs them (raw 64-byte
        Ed25519 attestation), and returns the host-captured fetched value
        alongside a receipt that verifies via
        ``verify_read_receipt(receipt, manifest, verifier)``. The receipt's
        ``observed_at`` datetime is reconstructed from the seam's fixed-width
        string so ``receipt.observed_at.isoformat(timespec="microseconds")``
        re-derives byte-identical signing bytes (P0-05 / spec §3).
        """
        canonical_bytes = self._seam.derive_read_bytes(observed)
        attestation = self._signing_key.sign(canonical_bytes)
        receipt = AttestedReadReceipt(
            read_id=uuid.UUID(observed.receipt_id),
            canonical_bytes=canonical_bytes,
            attestation=attestation,
            attester_delegate_id=observed.signer_delegate_id,
            observed_at=datetime.fromisoformat(observed.observed_at),
        )
        return observed.value, receipt
