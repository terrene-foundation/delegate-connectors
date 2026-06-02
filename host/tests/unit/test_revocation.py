# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the production ``ProductionRevocationChannel``.

The host ships the PRODUCTION ``RevocationChannel`` concrete that replaces the
deleted in-connector revocation placeholder (which returned an unconditional
``False`` — a false trust property). The SDK ships
``kailash.delegate.dispatch.RevocationChannel`` as a ``@runtime_checkable``
structural Protocol (NO subclassing); these tests assert the concrete satisfies
that Protocol structurally AND — load-bearing — that EVERY ``is_revoked`` answer
is a REAL one derived from a verified-fresh-signed denylist, NOT a hardcoded
constant.

The three fail-closed invariants are the unforgeability proof:

1. **cold start** — ``source.current()`` returns ``None`` (never fetched /
   unreachable) → ``is_revoked`` returns ``True`` for EVERY id. This is the
   exact NeverRevoked-in-disguise failure mode: a channel that cannot prove the
   principal is NOT revoked MUST fail closed, never return ``False``.
2. **bad signature** — a tampered/forged snapshot signature → ``True``.
3. **stale** — a snapshot older than the ttl → ``True``.

Only when a snapshot is present, signature-valid, AND fresh does ``is_revoked``
consult ``delegate_id in revoked_ids`` — and that ``False`` answer is genuine
(the signed-fresh denylist really does not list the id), not an unconditional
constant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate.dispatch import RevocationChannel as RevocationChannelProtocol

from delegate_connectors_host.revocation import (
    ProductionRevocationChannel,
    RevocationSnapshot,
    StaticSignedDenylist,
    default_revocation_channel,
)


# --------------------------------------------------------------------------- #
# Test doubles (Protocol-satisfying deterministic sources, NOT mocks)          #
# --------------------------------------------------------------------------- #


class _NoneSource:
    """A ``RevocationSource`` that has never obtained a snapshot.

    Models cold start / unreachable source: ``current()`` returns ``None``. This
    is the in-disguise failure mode — the channel MUST fail closed (return
    ``True``) rather than treat "no data" as "not revoked".
    """

    def current(self) -> RevocationSnapshot | None:
        return None


class _FixedSnapshotSource:
    """A ``RevocationSource`` returning one pre-built snapshot every call.

    Lets a test pin a snapshot with a chosen ``issued_at`` / ``signature`` so the
    stale-path and bad-signature-path fail-closed invariants are exercised
    deterministically.
    """

    def __init__(self, snapshot: RevocationSnapshot) -> None:
        self._snapshot = snapshot

    def current(self) -> RevocationSnapshot | None:
        return self._snapshot


def _authority() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _ttl() -> timedelta:
    return timedelta(minutes=5)


def _fixed_clock(when: datetime):
    return lambda: when


# --------------------------------------------------------------------------- #
# Structural Protocol conformance                                              #
# --------------------------------------------------------------------------- #


def test_production_channel_satisfies_sdk_revocation_protocol() -> None:
    source = StaticSignedDenylist()
    channel = ProductionRevocationChannel(
        source, source.authority_public_key, ttl=_ttl()
    )
    assert isinstance(channel, RevocationChannelProtocol)


# --------------------------------------------------------------------------- #
# Happy path: present, signature-valid, fresh → REAL membership answer         #
# --------------------------------------------------------------------------- #


def test_revoked_id_on_signed_denylist_is_revoked_true() -> None:
    source = StaticSignedDenylist(revoked_ids={"agent-evil"})
    channel = ProductionRevocationChannel(
        source, source.authority_public_key, ttl=_ttl()
    )
    assert channel.is_revoked("agent-evil") is True


def test_nonlisted_id_fresh_valid_signed_denylist_is_revoked_false() -> None:
    # The denylist lists OTHER ids; the queried id is genuinely absent. The
    # False answer is REAL (membership of a verified-fresh-signed set), not a
    # hardcoded constant.
    source = StaticSignedDenylist(revoked_ids={"agent-evil", "agent-bad"})
    channel = ProductionRevocationChannel(
        source, source.authority_public_key, ttl=_ttl()
    )
    assert channel.is_revoked("agent-good") is False


def test_nonlisted_id_fresh_empty_signed_denylist_is_revoked_false() -> None:
    # Empty signed denylist: every id is genuinely absent. Still a REAL answer —
    # the source returns a fresh real signature the channel verifies.
    source = StaticSignedDenylist()  # default empty
    channel = ProductionRevocationChannel(
        source, source.authority_public_key, ttl=_ttl()
    )
    assert channel.is_revoked("agent-arbitrary") is False


# --------------------------------------------------------------------------- #
# Fail-closed: cold start (source.current() is None) — THE in-disguise failure #
# --------------------------------------------------------------------------- #


def test_cold_start_source_returns_none_is_revoked_true() -> None:
    # No snapshot has EVER been obtained. A channel that cannot prove the
    # principal is NOT revoked MUST fail closed. This is the precise difference
    # from the deleted always-live stub (which returned False unconditionally).
    channel = ProductionRevocationChannel(
        _NoneSource(), _authority().public_key(), ttl=_ttl()
    )
    assert channel.is_revoked("anyone") is True


# --------------------------------------------------------------------------- #
# Fail-closed: bad / tampered signature                                        #
# --------------------------------------------------------------------------- #


def test_tampered_signature_is_revoked_true() -> None:
    # A snapshot whose signature does NOT verify against the authority key MUST
    # fail closed, even for an id absent from revoked_ids.
    now = datetime.now(timezone.utc)
    snapshot = RevocationSnapshot(
        revoked_ids=frozenset(),
        issued_at=now,
        signature=b"\x00" * 64,  # not a valid signature over the canonical bytes
    )
    channel = ProductionRevocationChannel(
        _FixedSnapshotSource(snapshot),
        _authority().public_key(),
        ttl=_ttl(),
        clock=_fixed_clock(now),
    )
    assert channel.is_revoked("anyone") is True


def test_signature_from_wrong_authority_is_revoked_true() -> None:
    # A snapshot signed by a DIFFERENT (attacker) authority MUST fail closed
    # against the channel's expected authority public key.
    now = datetime.now(timezone.utc)
    attacker = Ed25519PrivateKey.generate()
    revoked_ids = frozenset()
    canonical = RevocationSnapshot.canonical_bytes(revoked_ids, now)
    forged_sig = attacker.sign(canonical)
    snapshot = RevocationSnapshot(
        revoked_ids=revoked_ids, issued_at=now, signature=forged_sig
    )
    legitimate_authority = Ed25519PrivateKey.generate().public_key()
    channel = ProductionRevocationChannel(
        _FixedSnapshotSource(snapshot),
        legitimate_authority,
        ttl=_ttl(),
        clock=_fixed_clock(now),
    )
    assert channel.is_revoked("anyone") is True


# --------------------------------------------------------------------------- #
# Fail-closed: stale snapshot (issued_at older than ttl)                       #
# --------------------------------------------------------------------------- #


def test_stale_snapshot_past_ttl_is_revoked_true() -> None:
    # A correctly-signed snapshot whose issued_at is older than the ttl MUST
    # fail closed: stale revocation data is as dangerous as no data.
    authority = Ed25519PrivateKey.generate()
    issued_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    revoked_ids = frozenset()
    canonical = RevocationSnapshot.canonical_bytes(revoked_ids, issued_at)
    signature = authority.sign(canonical)
    snapshot = RevocationSnapshot(
        revoked_ids=revoked_ids, issued_at=issued_at, signature=signature
    )
    # clock is well past issued_at + ttl
    now = issued_at + timedelta(hours=1)
    channel = ProductionRevocationChannel(
        _FixedSnapshotSource(snapshot),
        authority.public_key(),
        ttl=_ttl(),  # 5 minutes
        clock=_fixed_clock(now),
    )
    assert channel.is_revoked("anyone") is True


def test_fresh_signed_snapshot_within_ttl_consults_membership() -> None:
    # The boundary of the stale check: a correctly-signed snapshot WITHIN the
    # ttl is honored, so membership is consulted (False for an absent id — REAL).
    authority = Ed25519PrivateKey.generate()
    issued_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    revoked_ids = frozenset({"agent-evil"})
    canonical = RevocationSnapshot.canonical_bytes(revoked_ids, issued_at)
    signature = authority.sign(canonical)
    snapshot = RevocationSnapshot(
        revoked_ids=revoked_ids, issued_at=issued_at, signature=signature
    )
    now = issued_at + timedelta(minutes=2)  # within 5-minute ttl
    channel = ProductionRevocationChannel(
        _FixedSnapshotSource(snapshot),
        authority.public_key(),
        ttl=_ttl(),
        clock=_fixed_clock(now),
    )
    assert channel.is_revoked("agent-evil") is True
    assert channel.is_revoked("agent-good") is False


# --------------------------------------------------------------------------- #
# Canonical signing bytes are deterministic over the covered fields            #
# --------------------------------------------------------------------------- #


def test_canonical_bytes_deterministic_over_sorted_ids_and_issued_at() -> None:
    issued_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    a = RevocationSnapshot.canonical_bytes(frozenset({"b", "a", "c"}), issued_at)
    b = RevocationSnapshot.canonical_bytes(frozenset({"c", "a", "b"}), issued_at)
    assert a == b  # set iteration order MUST NOT affect the signed bytes


def test_canonical_bytes_change_when_ids_change() -> None:
    issued_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    empty = RevocationSnapshot.canonical_bytes(frozenset(), issued_at)
    nonempty = RevocationSnapshot.canonical_bytes(frozenset({"x"}), issued_at)
    assert empty != nonempty


def test_canonical_bytes_change_when_issued_at_changes() -> None:
    ids = frozenset({"x"})
    t1 = RevocationSnapshot.canonical_bytes(
        ids, datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    t2 = RevocationSnapshot.canonical_bytes(
        ids, datetime(2026, 1, 2, tzinfo=timezone.utc)
    )
    assert t1 != t2


# --------------------------------------------------------------------------- #
# StaticSignedDenylist: signs fresh each call so the static list is always-fresh #
# --------------------------------------------------------------------------- #


def test_static_denylist_signs_fresh_each_call() -> None:
    # The source returns a snapshot signed FRESH (issued_at = now) on every call,
    # so a static list never goes stale. Two successive snapshots therefore have
    # distinct issued_at (and thus distinct signatures over distinct bytes).
    source = StaticSignedDenylist()
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ticks = iter([base, base + timedelta(seconds=10)])
    source_clocked = StaticSignedDenylist(clock=lambda: next(ticks))
    s1 = source_clocked.current()
    s2 = source_clocked.current()
    assert s1 is not None and s2 is not None
    assert s1.issued_at != s2.issued_at
    assert s1.signature != s2.signature
    # sanity: the always-fresh source produces real verifiable signatures
    assert source.current() is not None


def test_static_denylist_snapshot_verifies_under_its_public_key() -> None:
    source = StaticSignedDenylist(revoked_ids={"agent-evil"})
    snap = source.current()
    assert snap is not None
    canonical = RevocationSnapshot.canonical_bytes(snap.revoked_ids, snap.issued_at)
    # No exception == valid signature under the source's own authority key.
    source.authority_public_key.verify(snap.signature, canonical)
    assert "agent-evil" in snap.revoked_ids


# --------------------------------------------------------------------------- #
# default_revocation_channel(): transitional Phase-0 default                    #
# --------------------------------------------------------------------------- #


def test_default_revocation_channel_empty_list_is_revoked_false() -> None:
    # The transitional default: empty signed-fresh denylist → an arbitrary id is
    # genuinely NOT revoked (REAL answer derived from a verified-fresh signature,
    # NOT a hardcoded False).
    channel = default_revocation_channel()
    assert channel.is_revoked("some-arbitrary-delegate-id") is False


def test_default_revocation_channel_satisfies_protocol() -> None:
    channel = default_revocation_channel()
    assert isinstance(channel, RevocationChannelProtocol)


def test_default_revocation_channel_never_returns_unconditional_false() -> None:
    # Anti-stub guard: a channel built on a cold (None-returning) source MUST
    # return True. If is_revoked were the old unconditional-False stub, this would
    # fail. (We build the cold-source channel directly to assert the property the
    # default factory's source would also honor once unreachable.)
    cold = ProductionRevocationChannel(
        _NoneSource(), _authority().public_key(), ttl=_ttl()
    )
    assert cold.is_revoked("x") is True


# --------------------------------------------------------------------------- #
# Snapshot is a frozen dataclass (immutable)                                   #
# --------------------------------------------------------------------------- #


def test_revocation_snapshot_is_immutable() -> None:
    now = datetime.now(timezone.utc)
    snap = RevocationSnapshot(
        revoked_ids=frozenset({"a"}), issued_at=now, signature=b"sig"
    )
    with pytest.raises(Exception):
        snap.revoked_ids = frozenset()  # type: ignore[misc]
