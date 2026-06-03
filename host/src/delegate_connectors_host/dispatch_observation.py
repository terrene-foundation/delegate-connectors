# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""The host-observation seam (Phase-0, P0-08a).

This is the NET-NEW mechanism that closes the **forge oracle** architecture §2
verifies open today. The shipped connectors run the side-effect thunk INSIDE
their own ``write()`` / ``read()`` (``connector.py`` action thunk) and build the
canonical receipt bytes themselves — so a connector can hand the host a
*fabricated* "success" for a send the broker never performed, and a naive
host-side signer would sign it (the "sign a delivery that never happened" forge
of architecture §3.5 layer 2(b)).

The seam relocates the side-effect INVOCATION to the host:

1. The **host** invokes the brokered side effect through the opaque
   :class:`~delegate_connectors_host.bound_transport.BoundTransport` handle
   (``send`` for a write, ``fetch`` for a read). The connector supplies only the
   call arguments and a *pure* ``summarize`` projection — it never supplies the
   to-be-signed result.
2. The host **captures its own observation** of the return value, applies the
   connector's pure ``summarize`` to that host-captured value, and stamps the
   observation with a host-generated receipt id + a host-read
   ``observed_at`` (P0-05 fixed-width microseconds).
3. The host **derives canonical receipt bytes** from that host-observed payload
   via the shared P0-04 helpers (:func:`build_action_signing_bytes` /
   :func:`build_read_signing_bytes`), conforming to
   ``specs/canonical-signing-bytes.md`` §1–§6 (FROZEN v1).
4. The host **refuses to derive bytes for any side effect it did not itself
   observe**. The derive gate accepts ONLY an :class:`ObservedSideEffect` minted
   by this seam's own ``observe_*`` call; a fabricated or foreign ticket raises
   :class:`UnobservedSideEffectError`. There is no API path that turns a
   connector-supplied result into signable bytes without the host having invoked
   the brokered handle.

What this seam does NOT do (later shards)
=========================================
- **Signing** is P0-08b: the host holds the Ed25519 key and signs ONLY the bytes
  this seam derived. This module produces bytes and refuses; it never signs.
- **Wiring** the reference connectors onto the seam (relocating the
  ``connector.py`` action thunk so the connector loses action-invocation
  ownership) is **P0-09 / P0-11 (Wave 7)**. Like the credential broker (P0-07),
  this shard BUILDS + TESTS the seam but has no production call site yet — it is
  a transitional orphan, accepted per the Phase-0 plan
  (``workspaces/connector-platform/todos/active/00-phase0-decoupling-foundation.md``).

Distinct from the spine audit slot
===================================
The bytes this seam derives are the **connector-RECEIPT** pre-image
(``{action_id, observed_at, payload, signer_delegate_id}`` per
``specs/canonical-signing-bytes.md`` §2 / protocol-spec §2) — a DIFFERENT
pre-image and wire form from the SDK ``DispatchSurface`` audit-event slot
(``{event_type, event_payload, signer_delegate_id}``). The seam composes AROUND
the SDK dispatch surface; it makes ZERO edits to the ``kailash`` spine (a
separate repo — repo-scope discipline). It reaches the spine only through the
frozen receipt helpers re-exported by
:mod:`delegate_connectors_host.signing_bytes`.

See ``workspaces/connector-platform/02-plans/01-architecture.md`` §3.5 layer 2.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from weakref import WeakKeyDictionary

from delegate_connectors_host.bound_transport import BoundTransport
from delegate_connectors_host.signing_bytes import (
    build_action_signing_bytes,
    build_read_signing_bytes,
)

__all__ = [
    "DispatchObservationSeam",
    "ObservedSideEffect",
    "UnobservedSideEffectError",
    "Summarize",
]


# The connector-supplied projection: maps the HOST-captured raw return value to a
# canonical-JSON receipt payload. It MUST be pure (no I/O, no side effects) — the
# host applies it to the value the host itself observed. Kept structural so the
# seam never reaches into the connector's domain types.
#
# Trust-boundary note (explicit by design): the seam owns the side-effect
# INVOCATION (the host calls BoundTransport.send/fetch) and the OBSERVATION (the
# value handed to summarize is the host-captured return, never a connector-
# supplied result). The SHAPE of the projected payload is connector-controlled —
# the connector legitimately owns its own receipt schema. The seam does not
# schema-validate summarize's output beyond canonical-domain conformance
# (assert_canonical_signing_domain, applied inside the P0-04 helpers); tightening
# payload-shape provenance (e.g. validating against a declared receipt-payload
# contract) is deferred to the connector-wiring shards (P0-09 / P0-11).
Summarize = Callable[[Any], Mapping[str, Any]]


class UnobservedSideEffectError(ValueError):
    """Refusal: asked to derive bytes for a side effect this host did not observe.

    Raised by :meth:`DispatchObservationSeam.derive_action_bytes` /
    :meth:`~DispatchObservationSeam.derive_read_bytes` when handed an
    :class:`ObservedSideEffect` that this seam did not itself mint via an
    ``observe_*`` call — i.e. a fabricated ticket, a ticket from a different seam
    instance, or a ticket whose kind does not match the derive surface. This is
    the structural closure of the forge oracle: the host signs only what it
    itself brokered and observed.

    Subclasses :class:`ValueError` so a generic receipt-construction handler
    still catches it, while the concrete type names the specific refusal.
    """


@dataclass(frozen=True, eq=False)
class ObservedSideEffect:
    """An immutable, unforgeable ticket for a side effect THIS host observed.

    Minted ONLY by :meth:`DispatchObservationSeam.observe_action` /
    :meth:`~DispatchObservationSeam.observe_read`, which invoke the brokered
    handle, capture the return, and register the ticket in the seam's private
    ledger keyed by the ticket's **object identity**. ``eq=False`` makes the
    ticket identity-hashed: a fabricated instance carrying identical field values
    is a DIFFERENT object, absent from the ledger, and refused at derive time.
    The capability is the object identity, not any field a forger could copy.

    Attributes
    ----------
    kind:
        ``"action"`` (a write, via ``BoundTransport.send``) or ``"read"`` (via
        ``BoundTransport.fetch``). Selects the §2 pre-image shape and gates the
        matching derive surface.
    payload:
        The host's ``summarize`` projection of the host-captured return value —
        the receipt's ``payload`` (write) / ``manifest`` (read) field.
    value:
        The raw host-captured return of the brokered call. The dispatch path
        returns this to the caller (e.g. the fetched messages for a read); it is
        NOT part of the signed pre-image.
    signer_delegate_id:
        The dispatch identity bound as the receipt's signer (write) / attester
        (read) — supplied by the host at observation time.
    receipt_id:
        The host-generated ``action_id`` (write) / ``read_id`` (read), UUID
        string form (lowercase, hyphenated).
    observed_at:
        The host-read observation time, P0-05 fixed-width microseconds
        (``isoformat(timespec="microseconds")``, literal ``+00:00`` offset).
    """

    kind: str
    payload: Mapping[str, Any]
    value: Any
    signer_delegate_id: str
    receipt_id: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class _ObservationRecord:
    """The seam's private per-ticket record: the host-derived canonical bytes.

    The bytes are computed ONCE, at observation time, from the host-captured
    payload. The derive gate returns these recorded bytes after confirming the
    ticket is genuine — it never recomputes from caller-supplied state, so a
    forger cannot influence the bytes even by reconstructing the ticket's fields.
    """

    kind: str
    canonical_bytes: bytes


def _utcnow() -> datetime:
    """Default clock — current UTC time. Injectable for deterministic tests."""
    return datetime.now(timezone.utc)


def _fixed_width(observed_at: datetime) -> str:
    """Render ``observed_at`` as P0-05 fixed-width microseconds (spec §3).

    Always exactly 6 fractional digits with the literal ``+00:00`` offset — the
    byte-identical form the cross-impl verifier re-derives. A naive
    ``isoformat()`` would omit the fraction when microseconds are zero, breaking
    100% of cross-impl verifications silently (the retired 0.1.0 footgun).
    """
    if observed_at.tzinfo is None:
        raise ValueError(
            "observed_at MUST be timezone-aware (UTC); a naive datetime cannot "
            "render the spec-§3 fixed-width +00:00 offset"
        )
    return observed_at.astimezone(timezone.utc).isoformat(timespec="microseconds")


class DispatchObservationSeam:
    """Host-side observation seam — the host observes, then signs only what it saw.

    One seam instance owns one private ledger of the observations it has made.
    The seam is the sole minter of :class:`ObservedSideEffect` tickets and the
    sole holder of the derived canonical bytes; the derive surface refuses any
    ticket it did not itself mint.

    Parameters
    ----------
    clock:
        Returns the observation time. Defaults to :func:`_utcnow`; tests inject a
        fixed clock to reproduce the frozen conformance vectors byte-for-byte.
    new_receipt_id:
        Returns the host-generated receipt id (``action_id`` / ``read_id``).
        Defaults to :func:`uuid.uuid4`; tests inject a fixed id for determinism.
    """

    __slots__ = ("_clock", "_new_receipt_id", "_ledger")

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utcnow,
        new_receipt_id: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._clock = clock
        self._new_receipt_id = new_receipt_id
        # Ticket object-identity -> recorded bytes. WeakKey so a ticket the
        # caller drops is evicted automatically; the ledger never outgrows the
        # set of live, host-minted observations.
        self._ledger: "WeakKeyDictionary[ObservedSideEffect, _ObservationRecord]" = (
            WeakKeyDictionary()
        )

    # ── observation: the host invokes + captures the brokered side effect ─────

    async def observe_action(
        self,
        transport: BoundTransport,
        summarize: Summarize,
        /,
        *args: Any,
        signer_delegate_id: str,
        **kwargs: Any,
    ) -> ObservedSideEffect:
        """Invoke a brokered SEND host-side; mint a ticket over the captured return.

        The HOST calls ``transport.send(*args, **kwargs)`` and captures its own
        observation of the result. The connector-supplied pure ``summarize`` is
        applied to that host-captured value (never to a connector-supplied
        result). The observation is stamped with a host-generated ``action_id``
        and ``observed_at``, the canonical write bytes are derived and recorded,
        and the ticket is returned for P0-08b to sign.

        Reserved kwarg: ``signer_delegate_id`` is consumed by the host as the
        receipt signer and is NOT forwarded to ``transport.send`` — a brokered
        SEND that needs a literal ``signer_delegate_id`` argument MUST pass it
        positionally (via ``*args``). ``*args`` and all other ``**kwargs`` ARE
        forwarded straight through.
        """
        result = await transport.send(*args, **kwargs)
        return self._observe("action", result, summarize, signer_delegate_id)

    async def observe_read(
        self,
        transport: BoundTransport,
        summarize: Summarize,
        /,
        *args: Any,
        attester_delegate_id: str,
        **kwargs: Any,
    ) -> ObservedSideEffect:
        """Invoke a brokered FETCH host-side; mint a ticket over the captured return.

        The read counterpart of :meth:`observe_action`: the HOST calls
        ``transport.fetch(*args, **kwargs)``, captures the fetched value, applies
        the connector's pure ``summarize`` to build the read manifest, stamps a
        host-generated ``read_id`` + ``observed_at``, derives the canonical read
        bytes, and returns the ticket (``.value`` carries the raw fetched result
        the dispatch path returns to the caller).

        Reserved kwarg: ``attester_delegate_id`` is consumed by the host as the
        receipt attester and is NOT forwarded to ``transport.fetch`` — a brokered
        FETCH that needs a literal ``attester_delegate_id`` argument MUST pass it
        positionally (via ``*args``). ``*args`` and all other ``**kwargs`` ARE
        forwarded straight through.
        """
        result = await transport.fetch(*args, **kwargs)
        return self._observe("read", result, summarize, attester_delegate_id)

    def _observe(
        self,
        kind: str,
        result: Any,
        summarize: Summarize,
        signer_delegate_id: str,
    ) -> ObservedSideEffect:
        """Project the host-captured ``result``, stamp it, derive + record bytes."""
        payload = summarize(result)
        if not isinstance(payload, Mapping):
            raise TypeError(
                "summarize MUST return a mapping (the receipt payload / "
                f"manifest); got {type(payload).__name__!r}"
            )
        payload = dict(payload)
        receipt_id = str(self._new_receipt_id())
        observed_at = _fixed_width(self._clock())

        if kind == "action":
            canonical_bytes = build_action_signing_bytes(
                payload,
                signer_delegate_id=signer_delegate_id,
                action_id=receipt_id,
                observed_at=observed_at,
            )
        else:  # "read"
            canonical_bytes = build_read_signing_bytes(
                payload,
                attester_delegate_id=signer_delegate_id,
                read_id=receipt_id,
                observed_at=observed_at,
            )

        ticket = ObservedSideEffect(
            kind=kind,
            payload=payload,
            value=result,
            signer_delegate_id=signer_delegate_id,
            receipt_id=receipt_id,
            observed_at=observed_at,
        )
        self._ledger[ticket] = _ObservationRecord(
            kind=kind, canonical_bytes=canonical_bytes
        )
        return ticket

    # ── the refuse-on-unobserved derive gate ──────────────────────────────────

    def derive_action_bytes(self, observed: ObservedSideEffect) -> bytes:
        """Return the canonical WRITE bytes for a genuine action observation.

        Refuses (:class:`UnobservedSideEffectError`) any ticket this seam did not
        mint via :meth:`observe_action` — a fabricated ticket, a ticket from
        another seam, or a read ticket handed to the write surface.
        """
        return self._derive(observed, "action")

    def derive_read_bytes(self, observed: ObservedSideEffect) -> bytes:
        """Return the canonical READ bytes for a genuine read observation.

        Refuses (:class:`UnobservedSideEffectError`) any ticket this seam did not
        mint via :meth:`observe_read`.
        """
        return self._derive(observed, "read")

    def _derive(self, observed: ObservedSideEffect, kind: str) -> bytes:
        record = (
            self._ledger.get(observed)
            if isinstance(observed, ObservedSideEffect)
            else None
        )
        if record is None:
            raise UnobservedSideEffectError(
                "refusing to derive receipt bytes: this host did not observe the "
                "side effect (the ticket was not minted by this seam's "
                "observe_action/observe_read). The host signs only what it itself "
                "invoked and observed — a connector-fabricated result cannot be "
                "turned into signable bytes here."
            )
        if record.kind != kind:
            raise UnobservedSideEffectError(
                f"observation kind mismatch: ticket is a {record.kind!r} "
                f"observation but was handed to the {kind!r} derive surface"
            )
        return record.canonical_bytes
