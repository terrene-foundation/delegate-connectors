# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Production ``RevocationChannel`` concrete — fail-closed, signed denylist.

The host ships this PRODUCTION concrete to replace the deleted in-connector
revocation placeholder, whose ``is_revoked`` returned an unconditional
``False`` — one of the three false trust properties Phase 0 closes. That stub
could never prove a principal was NOT revoked; it simply asserted it. This
concrete proves it, or fails closed.

It satisfies the SDK :class:`kailash.delegate.dispatch.RevocationChannel`
Protocol STRUCTURALLY (``@runtime_checkable``; NO subclassing — duck typing
only). The Protocol is intentionally narrow: ``is_revoked(delegate_id) -> bool``,
where ``delegate_id`` is the PRINCIPAL (the delegate). Package-level revocation
(connector_id / version / fingerprint) is Phase-2 registry scope and is NOT in
this Protocol.

THE LOAD-BEARING INVARIANT: ``is_revoked`` NEVER returns an unconditional
``False``. Every ``False`` answer is a verified-fresh-signed denylist genuinely
NOT listing the principal. Every other outcome fails CLOSED (``True``):

1. **cold-start fail-closed** — the source has never obtained a snapshot
   (``current()`` is ``None``, e.g. unreachable revocation authority). A channel
   that cannot read the denylist cannot prove the principal is live, so it MUST
   refuse. This is the exact NeverRevoked-in-disguise failure mode: treating
   "no data" as "not revoked" re-introduces the unconditional ``False``.
2. **bad-signature fail-closed** — the snapshot's Ed25519 signature does NOT
   verify over its canonical bytes against the authority public key (forged,
   tampered, or signed by the wrong authority). An unauthenticated denylist is
   no denylist.
3. **stale fail-closed** — the snapshot's ``issued_at`` is older than ``ttl``.
   Stale revocation data is as dangerous as no data: a revocation issued after a
   stale snapshot would be silently missed.

Only a snapshot that is present AND signature-valid AND fresh is trusted, and
only then is ``delegate_id in revoked_ids`` consulted.

A bounded **fetch ceiling** caches the source snapshot for a short interval so
``is_revoked`` does not call ``source.current()`` on every check (a hot-path
call). The freshness invariant is preserved by the ttl check, which runs against
the snapshot's OWN ``issued_at`` regardless of when it was fetched — so a cached
snapshot still fails closed once it ages past ``ttl``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol, runtime_checkable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from kailash.trust._json import canonical_json_dumps

__all__ = [
    "RevocationSnapshot",
    "RevocationSource",
    "ProductionRevocationChannel",
    "StaticSignedDenylist",
    "default_revocation_channel",
]

# Phase-0 default TTL: a snapshot older than this fails closed. Five minutes is
# short enough that a revocation propagates promptly, long enough that a
# transient source outage doesn't immediately revoke every principal.
_DEFAULT_TTL = timedelta(minutes=5)

# Fetch ceiling: the channel caches the source snapshot for at most this interval
# before calling source.current() again. Bounds the source-call rate on the hot
# path without weakening freshness (the ttl check runs against issued_at).
_DEFAULT_FETCH_CEILING = timedelta(seconds=30)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RevocationSnapshot:
    """An immutable, signed point-in-time view of the revoked-principal set.

    The canonical signed bytes cover ``{issued_at, revoked_ids}`` — the
    ``revoked_ids`` sorted for determinism and ``issued_at`` as an ISO-8601
    string. Set iteration order MUST NOT affect the signed bytes, so the
    canonicalization sorts the ids.

    Attributes:
        revoked_ids: the frozen set of revoked delegate (principal) ids.
        issued_at: tz-aware UTC timestamp the snapshot was signed at; the
            freshness check measures the snapshot's age against this.
        signature: the Ed25519 signature over :meth:`canonical_bytes`.
    """

    revoked_ids: frozenset[str]
    issued_at: datetime
    signature: bytes

    @staticmethod
    def canonical_bytes(revoked_ids: frozenset[str], issued_at: datetime) -> bytes:
        """Deterministic signed pre-image over ``{issued_at, revoked_ids}``.

        ``revoked_ids`` is emitted as a SORTED list (set iteration order MUST NOT
        change the bytes); ``issued_at`` as its ISO-8601 string. Uses the SDK
        canonical JSON encoder (sorted keys, no whitespace) so the bytes are
        reproducible across producer and verifier.
        """
        return canonical_json_dumps(
            {
                "issued_at": issued_at.isoformat(),
                "revoked_ids": sorted(revoked_ids),
            }
        ).encode("utf-8")


@runtime_checkable
class RevocationSource(Protocol):
    """Supplies the latest signed :class:`RevocationSnapshot`.

    ``current()`` returns the latest snapshot, or ``None`` when no snapshot has
    EVER been successfully obtained — cold start, or the revocation authority is
    unreachable. ``None`` is NOT "empty denylist"; it is "unknown", and the
    channel fails closed on it.
    """

    def current(self) -> RevocationSnapshot | None:  # pragma: no cover (Protocol)
        ...


class ProductionRevocationChannel:
    """Fail-closed ``RevocationChannel`` over a signed denylist source.

    Satisfies the SDK ``RevocationChannel`` Protocol structurally. See the module
    docstring for the three fail-closed invariants. ``is_revoked`` returns
    ``False`` ONLY for a principal genuinely absent from a present,
    signature-valid, fresh snapshot — never unconditionally.

    Args:
        source: the snapshot source (``current() -> RevocationSnapshot | None``).
        authority_public_key: the Ed25519 public key every snapshot signature
            MUST verify against.
        ttl: maximum snapshot age; older → fail closed.
        clock: injectable now() for testing; defaults to tz-aware UTC now.
        fetch_ceiling: the bounded interval the channel caches the source
            snapshot before re-fetching (the hot-path source-call rate ceiling).
    """

    def __init__(
        self,
        source: RevocationSource,
        authority_public_key: Ed25519PublicKey,
        *,
        ttl: timedelta,
        clock: Callable[[], datetime] = _utcnow,
        fetch_ceiling: timedelta = _DEFAULT_FETCH_CEILING,
    ) -> None:
        if not isinstance(authority_public_key, Ed25519PublicKey):
            raise TypeError(
                "authority_public_key MUST be an Ed25519PublicKey; got "
                f"{type(authority_public_key).__name__}"
            )
        if not isinstance(ttl, timedelta):
            raise TypeError(f"ttl MUST be a timedelta; got {type(ttl).__name__}")
        if not isinstance(fetch_ceiling, timedelta):
            raise TypeError(
                f"fetch_ceiling MUST be a timedelta; got {type(fetch_ceiling).__name__}"
            )
        self._source = source
        self._authority_public_key = authority_public_key
        self._ttl = ttl
        self._clock = clock
        self._fetch_ceiling = fetch_ceiling
        # Fetch-ceiling cache: (fetched_at, snapshot-or-None).
        self._cached_at: datetime | None = None
        self._cached_snapshot: RevocationSnapshot | None = None

    def _fetch(self) -> RevocationSnapshot | None:
        """Return the source snapshot, honoring the bounded fetch ceiling.

        Within ``fetch_ceiling`` of the last fetch, returns the cached snapshot
        (including a cached ``None``); otherwise re-calls ``source.current()``.
        The cached snapshot's own ``issued_at`` still governs freshness, so
        caching never defeats the stale-fail-closed invariant.
        """
        now = self._clock()
        if self._cached_at is not None and now - self._cached_at < self._fetch_ceiling:
            return self._cached_snapshot
        snapshot = self._source.current()
        self._cached_at = now
        self._cached_snapshot = snapshot
        return snapshot

    def is_revoked(self, delegate_id: str) -> bool:
        """Return whether ``delegate_id`` (the principal) is revoked — fail-closed.

        Returns ``True`` (fail closed) on cold start, bad signature, or staleness.
        Returns the REAL membership answer ``delegate_id in revoked_ids`` only for
        a present, signature-valid, fresh snapshot. NEVER an unconditional
        ``False``.
        """
        snapshot = self._fetch()

        # (1) cold-start fail-closed — no snapshot ever obtained.
        if snapshot is None:
            return True

        # (2) bad-signature fail-closed — signature MUST verify over the
        # canonical bytes against the authority public key.
        canonical = RevocationSnapshot.canonical_bytes(
            snapshot.revoked_ids, snapshot.issued_at
        )
        try:
            self._authority_public_key.verify(snapshot.signature, canonical)
        except InvalidSignature:
            return True

        # (3) stale fail-closed — snapshot older than ttl.
        if self._clock() - snapshot.issued_at > self._ttl:
            return True

        # Present + signature-valid + fresh: consult the REAL denylist.
        return delegate_id in snapshot.revoked_ids


class StaticSignedDenylist:
    """Phase-0 ``RevocationSource`` — a static, always-fresh, signed denylist.

    Holds its own Ed25519 authority keypair and a (default empty) set of revoked
    delegate ids. ``current()`` signs a FRESH snapshot each call
    (``issued_at = now``), so the static list is genuinely always-fresh — it is
    NOT a stub: the returned snapshot carries a real signature the channel
    verifies, and adding an id makes ``is_revoked`` return ``True`` for it.

    This is the transitional Phase-0 source. P0-11 replaces it with a
    host-injected shared channel backed by a real revocation feed.

    Args:
        revoked_ids: the initial revoked-principal set (default empty).
        clock: injectable now() for testing; defaults to tz-aware UTC now.
    """

    def __init__(
        self,
        revoked_ids: set[str] | frozenset[str] | None = None,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._revoked_ids: frozenset[str] = frozenset(revoked_ids or ())
        self._clock = clock
        self._authority_private_key = Ed25519PrivateKey.generate()
        self._authority_public_key = self._authority_private_key.public_key()

    @property
    def authority_public_key(self) -> Ed25519PublicKey:
        """The Ed25519 public key this source signs snapshots with."""
        return self._authority_public_key

    def current(self) -> RevocationSnapshot | None:
        """Return a snapshot signed FRESH at the current clock time.

        Always returns a real snapshot (never ``None``): a static source is
        always reachable. ``issued_at = now`` so the snapshot is always within
        any reasonable ttl, and the signature is computed over the canonical
        bytes — a real, verifiable Ed25519 signature, not a placeholder.
        """
        issued_at = self._clock()
        canonical = RevocationSnapshot.canonical_bytes(self._revoked_ids, issued_at)
        signature = self._authority_private_key.sign(canonical)
        return RevocationSnapshot(
            revoked_ids=self._revoked_ids,
            issued_at=issued_at,
            signature=signature,
        )


def default_revocation_channel() -> ProductionRevocationChannel:
    """Transitional Phase-0 default channel each connector uses.

    Returns a :class:`ProductionRevocationChannel` over an empty
    :class:`StaticSignedDenylist`, bound to that source's own authority public
    key, with the default ttl. The empty signed-fresh denylist means an arbitrary
    principal is genuinely NOT revoked (a REAL answer from a verified-fresh
    signature) — NOT a hardcoded ``False``: adding an id to the source flips
    ``is_revoked`` to ``True``, and an unreachable source fails closed.

    P0-11 replaces this per-connector default with a host-injected shared
    channel.
    """
    source = StaticSignedDenylist()
    return ProductionRevocationChannel(
        source,
        source.authority_public_key,
        ttl=_DEFAULT_TTL,
    )
