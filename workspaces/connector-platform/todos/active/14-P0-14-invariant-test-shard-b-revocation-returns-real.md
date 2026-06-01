# P0-14 — Invariant TEST shard B — revocation returns REAL state (incl. cold-start) + delegate_host_protocol load-time refusal fires with portable kind

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~150 LOC
> **Depends on:** P0-02, P0-10b, P0-11
> **Implements:** architecture §7 Phase 0; architecture §3.3; specs host_protocol_contract; protocol-spec §6 §9; rules/zero-tolerance.md Rule 2

## What (≤3 sentences)

Cross-cutting invariant tests for the remaining two Phase-0 structural mechanisms. Assert revocation returns REAL state (a revoked principal is actually refused; fail-closed on BOTH stale AND cold-start/unreachable; NeverRevoked->False is gone), and the delegate_host_protocol intersection gate REFUSES an unsupported range at load time with the portable error taxonomy.

## Deliverable

A regression test module asserting (1) revocation consults a real source and refuses a revoked principal (fail-closed on stale AND cold-start), and (2) connector_builder() raises a loud load-time refusal exposing portable `kind == 'protocol.unsupported'` for a disjoint delegate_host_protocol range naming both ranges.

## Files touched

- tests/regression/test_revocation_real_state.py (new — cross-connector)
- tests/regression/test_host_protocol_gate.py (new)

## Invariants (MUST hold)

- a revoked (connector_id, version, fingerprint) is actually refused — revocation returns REAL state, never an unconditional False
- a stale denylist (past fetch ceiling) is fail-closed (principal treated as potentially-revoked)
- a cold-start / never-fetched / unreachable denylist is fail-closed (security MEDIUM finding — distinct from the stale path)
- a disjoint delegate_host_protocol range triggers a loud load-time refusal exposing portable `.kind == 'protocol.unsupported'` (not a bespoke local exception name) naming connector kind + connector range + host range
- no NeverRevokedChannel survives anywhere (grep assertion in the test)

## Value anchor

Architecture §7 Phase 0 ("delete the NeverRevokedChannel->False placeholder") + §3.3 (loud load-time refusal). Per zero-tolerance Rule 2: revocation must return REAL state, not a fake-live stub, on every path incl. cold start. The protocol gate turns a silent thousands-wide spine break into a coordinated migration.

## Acceptance criteria

- [ ] test proves revocation returns real state and is fail-closed on BOTH stale AND cold-start; zero NeverRevokedChannel remains
- [ ] test proves an unsupported delegate_host_protocol range is refused loudly at load time exposing portable `kind == 'protocol.unsupported'` naming both ranges
- [ ] tests assert real revocation with no fake-live stub (zero-tolerance Rule 2)

## Test plan

Unit/regression: place a principal on the signed denylist -> is_revoked True and the connector path refuses it; non-listed principal -> allowed; stale denylist -> fail-closed; never-fetched/unreachable denylist -> fail-closed (cold start); invalid denylist signature -> rejected. Protocol gate: compose a connector whose delegate_host_protocol is disjoint from H -> connector_builder raises exposing `.kind == 'protocol.unsupported'` and a message naming both ranges; overlapping range -> binds at max(S∩H). Grep: zero NeverRevokedChannel.
