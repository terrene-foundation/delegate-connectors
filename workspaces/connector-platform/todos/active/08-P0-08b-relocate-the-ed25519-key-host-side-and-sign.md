# P0-08b — Relocate the Ed25519 key host-side and sign over the P0-08a observation seam (connector holds neither key nor thunk)

> **STATUS: IMPLEMENTED 2026-06-03** (branch `feat/p0-wave4-host-side-signer`, PR pending).
> Built `delegate_connectors_host/dispatch_signing.py::HostSigner(seam, signing_key)` as a
> standalone transitional orphan (no connector wiring — that is P0-09/P0-11). `sign_action` /
> `attest_read` route through the seam's refuse-on-unobserved gate; no `sign(bytes)` surface,
> no key accessor. Receipts verify under the SDK `Ed25519Verifier` (raw-64B sig, µs observed_at).
> Built against the RUNTIME kailash 2.28.1 dispatch shapes (loom source was ahead:
> `SignedActionEnvelope.observed_at` exists in source but NOT in 2.28.1). 159 host tests pass
> (+11). Journal: 0005. Next: P0-10a (factory wires broker + seam + signer).

> **Milestone:** P0 — Decoupling foundation · **Load-bearing:** YES · **Wire todo:** no · **Est:** ~140 LOC
> **Depends on:** P0-08a
> **Implements:** architecture §3.5 layer 2 (b); architecture §2 (unforgeability false); specs host_signing_constraints; specs/canonical-signing-bytes.md §4; value-prioritization MUST-1

## What (≤3 sentences)

Relocate the Ed25519 signing key host-side and wire the host signer over the P0-08a host-observation seam: the host signs the canonical bytes the seam derived from the host-observed side effect, with a host-held key. The connector holds NEITHER the raw key NOR a signer thunk (a signer thunk is a forge oracle). Produces the raw-64-byte Ed25519 envelope. Split out of the original P0-08 per capacity HIGH finding — this holds <=4 invariants and a single primary call-graph path.

## Deliverable

A host-side signer in/around DispatchSurface that signs the P0-08a-derived canonical bytes with a host-held Ed25519 key, producing a raw-64B-signature envelope that verifies under the SDK Ed25519Verifier; the connector retains no key and no thunk.

## Files touched

- delegate_connectors_host/dispatch_signing.py (new — host-side signer over the P0-08a seam)
- delegate_connectors_host/connector_builder.py (factory wires the host signer — see P0-10a)
- connectors/email/src/delegate_connectors/email/connector.py:291-293 (the \_sign path the refactor replaces — connector loses raw key, see P0-09)

## Invariants (MUST hold)

- the connector holds NEITHER the raw Ed25519 key NOR a signer thunk (no forge oracle)
- the host signs ONLY the canonical bytes the P0-08a seam derived from the host-observed side effect (no sign-arbitrary-bytes path is reachable)
- raw-64-byte Ed25519 signature wire form preserved (canonical-signing-bytes §4)
- produced receipts verify under the SDK Ed25519Verifier (P0-03 binding via P0-10a)

## Value anchor

Architecture §3.5 layer 2 (b): signing MUST move host-side. §2 lists unforgeability as FALSE today (connector holds the raw key at connector.py:269, signs at :293). HIGHEST user-value (value-prioritization MUST-1). Brief success criterion: the public trust claim true at every moment.

## Acceptance criteria

- [x] signing happens host-side; the connector holds neither key nor thunk
- [x] the host signs only P0-08a-derived bytes (no arbitrary-bytes signing path)
- [x] produced receipts verify under Ed25519Verifier with raw-64B sig + microsecond observed_at

## Test plan

Unit: host signs a receipt for a side effect the P0-08a seam observed; verify the resulting envelope under the SDK Ed25519Verifier (raw-64B sig, microsecond timestamp); negative: a connector attempting to invoke a signer directly has no key and no thunk available; negative: the host cannot be asked to sign bytes not produced by the P0-08a seam. BUILD half of the cannot-forge invariant TEST in P0-13.
