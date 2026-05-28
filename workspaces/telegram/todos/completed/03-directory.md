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

## Verification (Wave 1 — 2026-05-28)

Completed. `src/delegate_connectors/telegram/directory.py` ships the dual-keyed
`TelegramPrincipalResolver`, the `ResolutionOutcome` carrier, and the closed-enum
`UnknownSenderDisposition` ({Accept, Reject, EscalateToHuman}; v0 maps unknown →
`Reject`, reserves `EscalateToHuman`).

Design notes:

- The resolver keys ONE `Principal` three symmetric ways — stringified integer
  `user_id` (`resolve_user_id`), stringified integer `chat_id`
  (`resolve_chat_id`), and `delegate_id` (`resolve_delegate_id`, the view
  `authenticate` uses). Stringification canonicalizes (`"007"` ≡ `7`, `"+7"` ≡
  `"7"`) so int and string keys collide on the same entry.
- `@username` is NEVER a key: `resolve_handle` is always fail-closed `Reject`
  (even when a numerically-equal id is registered), and passing a handle to an
  id resolver RAISES rather than silently missing — a ref-unsafe, mutable handle
  must never be mistaken for an unknown id (journal/0001).
- `bool` ids and non-`Principal` values are rejected at construction.

Evidence — Tier-1 unit suite (`tests/unit/test_directory.py`, 14 tests) covers
every acceptance line plus key symmetry, negative `chat_id`, int/string key
collision, handle-rejection (both paths), and the closed-enum set. Run:

```
PYTHONPATH=connectors/telegram/src .venv/bin/python -m pytest \
  connectors/telegram/tests/unit/test_directory.py -q
```

→ 14 passed. (Full Wave-1 unit suite: 41 passed.)
