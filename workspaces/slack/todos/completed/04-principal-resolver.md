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

## Verification (Wave 1)

Implements `specs/connector-contract.md` § authenticate + `02-plans/02-connector-spec.md` § Principal resolution, § Unknown-sender disposition.

Created `src/delegate_connectors/slack/directory.py`:

- `SlackPrincipalResolver` — dual-keyed: `_by_delegate_id` (PRIMARY — `resolve_delegate_id` drives `authenticate`) and `_by_slack_id` (secondary literal — `resolve_slack_id` drives payload attribution). v0 exact-match (ADR-S2). Built from a `dict[str, Principal]` keyed by Slack id; each stored id is shape-validated + case-significantly normalized at construction.
- `UnknownSenderDisposition` — closed enum `{Accept, Reject, EscalateToHuman}`; unknown identity → `Reject` (fail-closed). `EscalateToHuman` reserved.
- `ResolutionOutcome` — typed return (`principal` | `disposition`, `.accepted` property).
- Reuses `normalize_slack_id` from todo 03 (case-significant).

Invariants satisfied:

1. `delegate_id` is the primary resolution key; the Slack id is a secondary literal index only (test: same principal reachable via both keys; `authenticate` path uses `resolve_delegate_id`).
2. Unknown identity → `Reject` (closed enum), NEVER `Accept`, fail-closed — for both the delegate_id path AND the slack_id path (a malformed incoming Slack id also fails closed to `Reject` rather than propagating the shape error on the attribution path).
3. Normalization is case-significant (via `normalize_slack_id`) and applied identically to stored keys + incoming ids — a valid uppercase id resolves; a lowercased variant does not.

Acceptance mapping:

- known `delegate_id` → `Principal(delegate_id, tenant_id, claims)` ✓
- unknown `delegate_id` → `Reject` (never `Accept`) ✓
- Slack id resolves via secondary `by_slack_id` index, case preserved ✓
- workspace/team id carried in `Principal.claims`, NOT in the lookup key ✓ (test: `team_id` lives in `claims`; looking the team id up as a delegate_id or slack_id does NOT resolve).

Test result: covered by `connectors/slack/tests/unit/test_directory.py`. Full Wave-1 suite: **40 passed** (`PYTHONPATH=connectors/slack/src .venv/bin/python -m pytest connectors/slack/tests/unit -q`).
