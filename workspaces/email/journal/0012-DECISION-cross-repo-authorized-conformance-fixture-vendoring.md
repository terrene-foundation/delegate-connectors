# 0012 — DECISION: cross-repo authorization to vendor canonical conformance fixture

**Type:** DECISION (cross-repo authorization)
**Date:** 2026-05-27
**Authorizer:** jack@terrene.foundation (repo co-owner)
cross-repo-authorized: terrene-foundation/kailash-py

## Verbatim user authorization

In-session, the user (Jack Hong, jack@terrene.foundation) was presented with the
following specific bounded action and explicitly approved it:

> Target: `terrene-foundation/kailash-py`
>
> Bounded action: read-only fetch of `tests/fixtures/delegate-conformance/canonical.json`
> → vendor into this repo (`delegate-connectors`) for use by the conformance runner.

User reply: **"yes approve F1, all 3 for F3 in parallel"** (verbatim).

That message followed an agent restatement of the exact target + action, so per
`rules/repo-scope-discipline.md` § User-Authorized Exception conditions 1–5 are
satisfied (user-initiated, explicit + specific, confirmed, scope-bounded). This
journal entry IS the pre-action receipt that closes condition 4 (journaled
before acting).

## Scope (exactly, no widening)

- **Permitted reads:** `terrene-foundation/kailash-py` repository contents,
  read-only, limited to the `tests/fixtures/delegate-conformance/` directory.
  The single load-bearing file is `canonical.json`; any sibling fixture files in
  the same directory required to make the canonical set load (schema-referenced
  helpers, README) MAY be read incidentally to verify the fixture is complete.
- **Permitted writes:** local-only — vendoring the fetched bytes into this
  repo at the path the conformance runner will load from. NO writes against
  `kailash-py` (no issues, no PRs, no comments).
- **Excluded:** any other directory of `kailash-py`; any other repo; any write
  back upstream. Out of scope.

## Action plan

1. (this entry) — journal receipt landed.
2. `gh api repos/terrene-foundation/kailash-py/contents/tests/fixtures/delegate-conformance/canonical.json`
   to fetch the fixture (or `gh repo view` + raw URL).
3. Vendor to `tests/fixtures/delegate-conformance/canonical.json` (monorepo
   root — shared across connectors; matches `specs/conformance.md` design).
4. Verify the fixture loads against `ConformanceVector` (frozen dataclass at
   `kailash/delegate/conformance/schema.py`) — every record parses, ids are
   unique, expected values are in the closed enum `{Accept, Reject, EscalateToHuman}`.
5. Land the F1 work on a `feat/conformance-fixture` branch + PR.

## Why this isn't reopened later

This authz is **single-use, scope-bounded**. A future need to read other
`kailash-py` paths (e.g. spec text for vector authoring per `specs/conformance.md`
option C) requires a fresh authorization — this receipt does NOT widen to other
paths or other repos. The standing instruction "if you need more, ask" stands.

## Cross-references

- `rules/repo-scope-discipline.md` § User-Authorized Exception
- `specs/conformance.md` § Resolution options — Option A (vendor)
- `workspaces/email/journal/0003-DECISION-build-shipped-api-defer-conformance.md`
  (the original deferral; this entry is the un-deferral receipt)
- `workspaces/email/journal/0009-DECISION-cross-repo-authorized-sdk-bug-filing.md`
  (sibling cross-repo authz — same shape, different action: SDK bug filing)
