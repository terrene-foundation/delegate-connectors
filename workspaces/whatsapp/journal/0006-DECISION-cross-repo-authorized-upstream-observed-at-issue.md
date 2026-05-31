# 0006 — DECISION: cross-repo authorized upstream kailash issue (observed_at)

**Type**: DECISION (cross-repo authorization receipt)
**Date**: 2026-05-31
cross-repo-authorized: terrene-foundation/kailash-py

## Authorization (repo-scope-discipline.md § User-Authorized Exception)

- **Requester**: jack@terrene.foundation (session owner)
- **Target repo**: `terrene-foundation/kailash-py` (upstream SDK BUILD repo)
- **Action**: file ONE GitHub issue — title `feat(delegate): SignedActionEnvelope
should carry observed_at as a first-class field` — with the scrubbed body
  presented in-session (5-section minimal-repro shape, no consumer identifiers).
- **Verbatim instruction**: "approved" — given in direct response to the agent
  restating the exact drafted issue + target repo and asking the user to say
  "file it" to submit.
- **Scope**: exactly this one issue against exactly this one repo. No other
  cross-repo reads/writes authorized.

All five conditions hold: user-initiated, explicit+specific (named repo + exact
issue), confirmed (agent restated; user approved), journaled-before-acting (this
entry lands before `gh issue create`), scoped exactly.

**Filed**: terrene-foundation/kailash-py#1209 (2026-05-31).

## Hygiene (upstream-issue-hygiene.md)

Body is scrubbed: no project name ("delegate-connectors"), no workspace paths,
no finding tags ("HIGH-1"), no internal file paths. Contains only the
`kailash.delegate.dispatch` API surface + a minimal repro using only `kailash`
imports + acceptance criteria. Human gate satisfied (user approved the shown
draft before submission).

## Context

HIGH-1 from the 2026-05-30 connectors /redteam: `SignedActionEnvelope` has no
first-class `observed_at` field (committed in canonical_bytes but not
re-derivable from the envelope, unlike `AttestedReadReceipt.observed_at`). An
API-ergonomics gap, not a forge vector. Root-cause fix is upstream rather than
a connector-payload workaround. See `04-validate/01-redteam-convergence-2026-05-30.md`.
