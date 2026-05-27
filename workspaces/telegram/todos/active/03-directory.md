# Todo 03 — Dual-keyed principal resolver / directory wiring

**Implements:** `specs/connector-contract.md` § Type catalog (`Principal`)
(+ `02-plans/02-connector-spec.md` § Principal resolution + § Unknown-sender disposition)
**Type:** Build · **Capacity:** single shard (~150 LOC, 3 invariants)
**Depends:** 01

## Do

- `src/delegate_connectors/telegram/directory.py` — resolve a Telegram identity to a
  `Principal` via a dual-keyed resolver. v0 keys by stringified integer `user_id` AND
  `chat_id`, plus the `delegate_id` view `authenticate` uses (journal/0001: integer ids
  are ref-safe and pass the `DelegateIdentity` `^[a-zA-Z0-9_-]+$` regex).
- `@username` handles are NEVER a resolution key (ref-unsafe `@` + mutable; journal/0001)
  — a supplied handle resolves to fail-closed `Reject`.
- `UnknownSenderDisposition` closed enum mapping unknown identity →
  `Reject` (NOT `Accept`), matching the conformance closed enum
  `{Accept, Reject, EscalateToHuman}`. `EscalateToHuman` reserved for a later policy shard.

## Invariants (3)

1. 3-way keying is symmetric: the same `Principal` is reachable via `delegate_id`,
   stringified `user_id`, and `chat_id`.
2. `@username` handle never resolves (ref-unsafe + mutable) → fail-closed `Reject`.
3. Unknown identity → `Reject` (fail-closed), never `Accept`.

## Acceptance

- [ ] Unit: known `user_id` → `Principal(delegate_id, tenant_id, claims)`.
- [ ] Unit: known `chat_id` resolves to the same `Principal` as its paired `user_id`.
- [ ] Unit: unknown identity → `Reject` (never `Accept`).
- [ ] Unit: `@handle` input → `Reject` (handle is never a key).
