# DECISION — Email connector shard plan (9 shards, conformance deferred)

**Date:** 2026-05-27
**Phase:** /todos

## Shard breakdown (all within capacity budget)

01 scaffold → 02 SMTP → 03 IMAP → 04 directory → 05 connector core (load-bearing,
~280 LOC / 6 invariants) → 06 wire runtime (end-to-end) → 07 Tier-1 → 08 Mailpit
Tier-2/3 → 09 README correction. Dependency order: 02/03/04 depend only on 01 (may
parallelize); 05 composes them; 06 wires runtime; 07/08 test; 09 docs.

Build/Wire split honored: 05 builds the connector; 06 wires it into a real
`DelegateRuntime` with no mocks.

## RISK

- **Audit-thunk semantics** (todo 05) are the main implementation risk: `read`/`write`
  take a zero-arg async thunk run under audit, and the receipts MUST be non-empty/
  verifiable (the exact failure mode that disqualified `LegacyInvokeConnector`). Tier-1
  (07) asserts non-empty receipts; Tier-2 (08) asserts they verify under the real
  `Ed25519Verifier`.
- **Fixture signature** (todo 06): v0 supplies a minimal application `signature`. It is
  a documented v0 placeholder (real signatures are application-supplied per the spine
  design), NOT a stub-for-production — flagged so /redteam doesn't mis-class it.

## Out of cycle

Conformance (deferred, value-anchored — `journal/0003`). README correction (09) is in
cycle but ships as a separate doc commit.

## Gate

User pre-authorized autonomous drive to /redteam convergence (`/autonomize` +
"/redteam to convergence" + "continue"), and approved scope via AskUserQuestion
(shipped-API reality + conformance deferral). The /todos plan is surfaced for
visibility; proceeding to /implement under the user's envelope rather than a hard stop.
