# Todo 04 — Principal resolution / directory wiring

**Implements:** `specs/connector-contract.md` § Methods (`authenticate`) (+ `02-plans/02-connector-spec.md` § Principal resolution, § Unknown-sender disposition)
**Type:** Build · **Capacity:** single shard (~180 LOC, 3 invariants)
**Depends:** 01, 02

**Value-anchor:** delivers the brief acceptance criterion "`authenticate()` resolves a known WhatsApp identity to a `Principal`; unknown → `ConnectorAuthenticationError` (fail-closed Reject) BEFORE any API call fires on the `invoke` hot path."

## Do

- `src/delegate_connectors/whatsapp/directory.py`:
  - `WhatsAppPrincipalResolver` — resolve by `delegate_id` (the shipped `DelegateIdentity`
    validates ref fields against `^[a-zA-Z0-9_-]+$` and cannot carry a `+`-prefixed
    number, so `authenticate` keys on `delegate_id`; the literal phone number lives on
    the message payload). Also keyed by normalized E.164 (reuse todo 02's normalizer)
    for the inbound-sender resolution path.
  - `UnknownSenderDisposition` — closed enum mirroring `{Accept, Reject, EscalateToHuman}`.
  - `ResolutionOutcome` — known → `Principal(delegate_id, tenant_id, claims)`;
    unknown → `REJECT` (fail-closed). `EscalateToHuman` reserved for a later policy shard.

## Invariants (3)

1. Exact-match only in v0 (alias / group resolution out of scope — do not add).
2. Unknown sender → `Reject` disposition, NOT `Accept`. Fail-closed default.
3. E.164 normalization is symmetric — applied identically to stored keys and incoming values.

## Acceptance

- [ ] Unit (Tier-1): known `delegate_id` → `Principal(delegate_id, tenant_id, claims)`.
- [ ] Unit: unknown identity → `Reject` (never `Accept`).
- [ ] Unit: normalization round-trips (a stored E.164 and the same number in an alternate
      surface form resolve to the same key).

## Verification

Completed in /implement Wave 1 (2026-05-28).

- `src/delegate_connectors/whatsapp/directory.py` created:
  `WhatsAppPrincipalResolver` (dual-keyed by `delegate_id` and normalized E.164,
  reusing todo 02's `normalize_e164`); `UnknownSenderDisposition` closed enum
  `{Accept, Reject, EscalateToHuman}`; `ResolutionOutcome` (known → Principal +
  ACCEPT; unknown → None + REJECT, fail-closed).
- Tier-1 tests `tests/unit/test_directory.py` — 8 tests, all green:
  - Known `delegate_id` → `Principal(delegate_id, tenant_id, claims)` + ACCEPT.
  - Unknown identity (delegate_id and phone) → REJECT, never ACCEPT.
  - Phone normalization round-trips: a stored `+1 (415) 555-0100` resolves
    identically from a bare-digit `14155550100` and a `+`-prefixed form.
  - Un-normalizable phone fails closed to REJECT.
  - Disposition enum is exactly the closed conformance set.
  - Non-Principal mapping values raise `TypeError`.
- All 3 invariants hold: exact-match only, no alias/group (1); unknown → REJECT,
  fail-closed (2); E.164 normalization symmetric across stored keys and incoming
  values (3).
