# P0-01 — Build production KnowledgeLedger concrete (durable, credentials-never-recorded invariant)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~120 LOC
> **Depends on:** none — Wave 1 (no deps)
> **Implements:** architecture §7 Phase 0; specs trust_primitive_interfaces (KnowledgeLedger); specs/connector-contract.md §Properties

## What (≤3 sentences)

Build a production KnowledgeLedger concrete replacing the four duplicated InMemoryKnowledgeLedger placeholders. Provide a durable backend behind the same structural Protocol (record(event_type, payload)->None append-only; records property->tuple). Preserve the invariant that records never carry credentials.

## Deliverable

A new shared `delegate_connectors_host/ledger.py` (or equivalent host module) exporting a production KnowledgeLedger concrete satisfying the SDK Protocol, with a durable append-only backend and a `records` inspection property.

## Files touched

- delegate_connectors_host/ledger.py (new shared host module)
- connectors/email/src/delegate_connectors/email/connector.py:82 (InMemoryKnowledgeLedger placeholder — replaced via property in P0-09)

## Invariants (MUST hold)

- record() is append-only; no mutation or deletion of prior entries
- records property returns an immutable tuple snapshot
- ledger NEVER stores credentials — only event_type + non-secret payload (specs trust_primitive_interfaces invariant)
- satisfies the SDK KnowledgeLedger Protocol structurally (no subclassing)

## Value anchor

Architecture §7 Phase 0: "ship production trust-primitive concretes (KnowledgeLedger/RevocationChannel/AuthVerifier)". The ledger is the knowledge trail behind the §2 "tamper-evident audit chain ✅ real" property — Phase 0 hardens the placeholder into a durable concrete.

## Acceptance criteria

- [ ] Production KnowledgeLedger concrete exists in a shared host module and satisfies the SDK Protocol structurally
- [ ] record() is append-only and records returns an immutable tuple
- [ ] no credential ever enters a ledger record (verified by the P0-11 wiring test)

## Test plan

Unit: record() then assert records snapshot equals input; assert append-only (second record extends, never replaces). Structural-conformance test: instance satisfies the SDK Protocol. The no-credential invariant is enforced by the P0-11 wiring test (connector forwards only event_type + non-secret payload).
