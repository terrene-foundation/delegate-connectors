---
type: DECISION
date: 2026-06-03
created_at: 2026-06-03T09:30:00Z
author: co-authored
session_id: term-21832
session_turn: 40
project: connector-platform
phase: implement
topic: P0-08b host-side Ed25519 signer over the P0-08a seam; built against runtime kailash shapes (loom source was ahead)
tags:
  [phase-0, p0-08b, forge-oracle, host-side-signing, ed25519, runtime-vs-source]
---

## Context

Wave 4 of Phase 0. P0-08b is the SECOND of the three composed mechanisms that close
the forge oracle (P0-08a host-observation seam — merged Wave 3 · **P0-08b host-side
signer** · P0-09/P0-11 connector loses action-invocation ownership). Today the
connector holds the raw Ed25519 key (`connector.py:160`) and signs in `_sign`
(`connector.py:184`); architecture §3.5 layer 2(b) names handing the connector a
signer thunk a forge oracle. P0-08b relocates the key host-side.

## Decisions

1. **Built `delegate_connectors_host/dispatch_signing.py`** — `HostSigner(seam,
signing_key)`. The host holds the Ed25519 key; `sign_action(observed)` →
   `SignedActionEnvelope` and `attest_read(observed)` → `(value,
AttestedReadReceipt)`. Both take an `ObservedSideEffect` ticket and route
   through the seam's `derive_*_bytes` gate, so they sign ONLY bytes the host
   itself observed. Receipts verify under the SDK `Ed25519Verifier` (raw-64-byte
   signature per spec §4).

2. **No sign-arbitrary-bytes surface — the structural closure.** `HostSigner`
   exposes ONLY `sign_action` / `attest_read` (asserted by test); there is no
   `sign(bytes)` method and no signing-key accessor (`__slots__`, key private). A
   fabricated / foreign-seam / wrong-kind ticket raises
   `UnobservedSideEffectError` and produces NO signature. "The host cannot be
   asked to sign bytes not produced by the P0-08a seam" is therefore structural,
   not conventional.

3. **Built against the RUNTIME kailash 2.28.1 shapes, NOT the loom source.**
   Reading the SDK dispatch types two ways surfaced a divergence: the loom
   `kailash-py` source has `SignedActionEnvelope.observed_at: datetime` (GH #1209),
   but the INSTALLED runtime (`.venv`, kailash 2.28.1) `SignedActionEnvelope` has
   NO `observed_at` field — the loom source is ahead of the published runtime.
   The connectors pass against the runtime (their `write()` constructs the
   envelope without `observed_at`). Building `HostSigner` against the loom source
   would have shipped an envelope with an unexpected kwarg. **Disposition: build
   against the installed runtime** (zero-tolerance — build against what is
   actually imported; `.venv` is the source of truth, not a sibling repo's HEAD).
   `AttestedReadReceipt.observed_at` IS a required `datetime` in 2.28.1, so the
   signer reconstructs it from the seam's fixed-width string via
   `datetime.fromisoformat` (lossless round-trip: `receipt.observed_at.isoformat(
timespec="microseconds")` re-derives the byte-identical signed timestamp,
   verified by `verify_read_receipt`).

4. **Scope: signer only, no connector wiring.** Like the broker (P0-07) and the
   seam (P0-08a), this shard builds + tests the signer as a transitional orphan
   with no production call site yet. Wiring the 4 connectors onto the host signer
   (so the connector loses its raw key at `connector.py:160`/`:184`) is P0-09 /
   P0-11. Zero kailash spine edits — the signer composes around the SDK dispatch
   types, constructing them from host-observed state.

## Consequences

- **159 host tests pass** (+11 this shard). The 11 cover: action + read receipts
  verify under the real SDK `Ed25519Verifier`; the host signs EXACTLY the
  seam-derived bytes (no drift); raw-64-byte sig; microsecond `observed_at`
  round-trip; forge negatives (fabricated / wrong-kind / foreign-seam tickets
  refused); no sign-arbitrary surface; key private; type guards; identity binding
  (same payload → distinct signatures via distinct `action_id`).
- User-flow walk (verbatim): host signs an observed action → 64-byte sig →
  verifies True under the SDK verifier; a fabricated success ticket → host
  refuses to sign; `HostSigner` public surface = `{sign_action, attest_read}`,
  no key accessor.
- Forge closure now has TWO of three mechanisms (P0-08a observe + P0-08b sign).
  The third (P0-09/P0-11 connector loses invocation ownership) + the P0-13
  adversarial fabricated-result test remain before unforgeability can be claimed.
- Critical path: `… → P0-08a → P0-08b → **P0-10a** (connector_builder factory
wires broker + seam + signer) → P0-10b → P0-11 → …`.

## For Discussion

1. The runtime/source divergence (loom `SignedActionEnvelope` has `observed_at`,
   runtime 2.28.1 does not) means a future kailash bump could make `observed_at`
   a required envelope field. Building against the runtime is correct now — but
   should the host pin a `kailash` floor that guarantees the dispatch-type shape,
   or add a construction-time shape probe so the bump surfaces loudly rather than
   as a silent missing-field at P0-10a wiring time?
2. `HostSigner` is bound to ONE seam and refuses tickets from any other seam
   instance. That is the correct forge coupling (a ticket is only signable by the
   signer over the seam that observed it) — but at P0-10a/P0-11, does the factory
   construct exactly one (seam, signer) pair per connector, and what happens to
   in-flight tickets if a connector is rebuilt (new seam) mid-session?
3. The read path reconstructs `observed_at` via `datetime.fromisoformat`. If a
   future spec vector used an offset other than `+00:00` or a non-6-digit
   fraction, would the round-trip still be byte-identical — or does the P0-05
   fixed-width invariant (always UTC `+00:00`, always 6 digits) need to be
   re-asserted at the signer boundary as well as the seam boundary?
