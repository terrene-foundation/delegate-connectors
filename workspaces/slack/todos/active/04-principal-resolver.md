# Todo 04 — Principal resolver (`directory.py`)

**Implements:** `specs/connector-contract.md` § authenticate (+ `02-plans/02-connector-spec.md` § Principal resolution, § Unknown-sender disposition)
**Type:** Build · **Capacity:** single shard (~150 LOC, 3 invariants)
**Depends:** 01, 03 (uses `normalize_slack_id`)

## Do

- `src/delegate_connectors/slack/directory.py`:
  - `SlackPrincipalResolver` — dual-keyed (mirrors email's `EmailPrincipalResolver`):
    a `by_delegate_id` index (PRIMARY — drives `authenticate`) and a `by_slack_id`
    index (secondary literal — drives payload attribution). v0 = exact-match lookup
    of the dispatch identity's `delegate_id` (ADR-S2).
  - `UnknownSenderDisposition` — a closed enum aligned to the conformance closed
    enum `{Accept, Reject, EscalateToHuman}`; an unknown identity resolves to
    `Reject` (fail-closed; not `Accept`). `EscalateToHuman` reserved for a later
    policy shard.
  - `ResolutionOutcome` — the resolver's typed return shape.
  - The team/workspace id lives in `Principal.claims` for forward-compat with
    multi-workspace OAuth (a later shard) WITHOUT entering the v0 lookup key.

## Invariants (3)

1. `delegate_id` is the primary resolution key (Slack id is a secondary literal
   index only).
2. Unknown identity → `Reject` (closed enum), NEVER `Accept`. Fail-closed.
3. Normalization is case-significant (via `normalize_slack_id` from todo 03) and
   applied consistently to stored + incoming Slack ids.

## Acceptance

- [ ] Unit: known `delegate_id` → `Principal(delegate_id, tenant_id, claims)`.
- [ ] Unit: unknown `delegate_id` → `Reject` (never `Accept`).
- [ ] Unit: a Slack id resolves via the secondary `by_slack_id` index with case
      preserved (not lowercased).
- [ ] Unit: workspace/team id is carried in `Principal.claims`, not in the lookup key.
