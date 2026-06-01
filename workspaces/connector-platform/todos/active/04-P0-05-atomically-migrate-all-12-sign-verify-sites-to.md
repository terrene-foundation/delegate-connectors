# P0-05 — Atomically migrate all 12 sign/verify sites to isoformat(timespec='microseconds') + commit interop fixtures

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~100 LOC
> **Depends on:** P0-04
> **Implements:** specs notes #2; specs notes #3; specs/canonical-signing-bytes.md §3; specs timestamp_form_sites; specs sign_verify_call_sites; specs/conformance.md (GATED canonical-vector provenance)

## What (≤3 sentences)

Switch every one of the 12 sign/verify call sites from bare .isoformat() (retired omit-when-zero form) to .isoformat(timespec='microseconds') in ONE shard. A partial migration silently breaks 100% of cross-impl verification with the Rust dc-enterprise tier. Commit the receipt-interop conformance fixtures (vectors A-E + reject suite) in the SAME shard so a green behavioral run cannot mask a byte-level break. NOTE: this remains 12 call-site edits regardless of P0-04 — the helpers take observed_at as a pre-formatted STRING (specs notes #2), so the dependency on P0-04 is for helper/fixture STABILITY (one shared helper to run vectors against), NOT for collapsing 12 edits to 1.

## Deliverable

All 12 call sites emit fixed-width 6-digit-microsecond observed_at (e.g. 2026-06-01T12:00:00.000000+00:00, +00:00 not Z), plus the committed receipt-interop fixture set under tests/fixtures/receipt-interop/ as the regression gate.

## Files touched

- connectors/email/src/delegate_connectors/email/connector.py:209,355,395
- connectors/slack/src/delegate_connectors/slack/connector.py:223,375,418
- connectors/telegram/src/delegate_connectors/telegram/connector.py:223,373,416
- connectors/whatsapp/src/delegate_connectors/whatsapp/connector.py:240,441,484
- tests/fixtures/receipt-interop/ (commit + wire vectors A-E + reject suite)

## Invariants (MUST hold)

- all 12 sites use isoformat(timespec='microseconds') — fixed-width 6-digit microseconds even when zero (canonical-signing-bytes §3)
- timezone suffix is +00:00, NOT Z
- the switch is ATOMIC in one commit — no connector left on bare isoformat() mid-flight
- the helpers take observed_at as a STRING; the form fix lives at the 12 CALL SITES (specs notes #2), not in the helper — the migration is 12 call-site edits, NOT a single-helper edit (corrected rationale per completeness LOW finding)
- interop fixtures are committed in the SAME shard — behavioral pass alone is NOT sufficient for interop (specs notes #3)
- fixture-provenance honesty: the committed A-E vectors' provenance MUST be stated — if locally-authored (not the canonical kailash-py cross-repo vectors, which specs/conformance.md flags GATED/BLOCKED), the gate is a byte-STABILITY regression gate, NOT a proven cross-impl interop gate; the value_anchor MUST NOT overclaim 'receipt-interop with the Rust tier' until canonical vectors are vendored (security LOW finding)

## Value anchor

specs notes #2: the isoformat switch is ATOMIC per canonical-signing-bytes §3 — a partial switch silently breaks 100% of cross-impl verification with the Rust dc-enterprise tier. The atomic-timestamp-migration trap from the session notes. Brief success criterion: the public trust claim true at every moment.

## Acceptance criteria

- [ ] all 12 sign/verify sites emit fixed-width microsecond observed_at with +00:00 suffix; zero bare .isoformat() at sign/verify sites
- [ ] the migration lands in ONE atomic commit (no partial state)
- [ ] receipt-interop fixtures (A-E + reject) are committed in the same shard and pass byte-level; fixture provenance is documented and the claim is scoped to what the fixtures actually prove

## Test plan

Interop conformance: run vectors A-E + the reject suite (canonical-signing-bytes §6) and assert byte-level match against the committed fixtures; assert observed_at is always 6-digit microseconds incl. when zero, suffix +00:00 not Z. Grep: zero bare `.isoformat()` at sign/verify sites (all carry timespec='microseconds'). State fixture provenance in the fixture README: locally-authored => byte-stability gate; canonical-vendored => cross-impl interop gate (file a follow-up referencing conformance.md BLOCKED status if vendoring is required).
