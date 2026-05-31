# F2 Shard Plan — un-xfail + pin bump (all 4 connectors)

**Phase**: /todos candidate · **Date**: 2026-05-31 · Feeds `/implement`.
Source analysis: `01-analysis/04-f2-unxfail-analysis.md`. Sharded per
`rules/autonomous-execution.md` § Per-Session Capacity Budget.

## Sharding rationale

Work-class A (pin) is orchestrator-owned and lands first (single writer of the 4
`pyproject.toml` floors — `rules/agents.md` § version-owner). Work-class E (the
conformance driver) is the dense load-bearing core; it is designed ONCE on slack,
then replicated. Each connector then gets one shard applying B/C/D/E to it. Email
carries the extra mailpit-infra dependency.

## Shards

### Shard 0 — Pin bump + spec status (orchestrator, lands first)

- 4× `connectors/*/pyproject.toml`: `kailash>=2.26.1` → `kailash>=2.28.0` (floor; uncapped per `rules/dependencies.md`).
- Install kailash 2.28.1 into the dev `.venv` (currently 2.26.2).
- `specs/conformance.md`: flip STATUS from "HALF-ACTIVE / gated on #1182" toward "ACTIVE"; record the per-vector wiring is in progress (final flip at Shard 5 close).
- **Size**: boilerplate, ~5 invariants none. Single shard.
- **Gate**: full suite green on 2.28.1 with markers STILL in place (so the clean-flips show as XPASS-strict-fail — expected, resolved in connector shards).

### Shard 1 — Conformance driver design (slack first; the hard core — class E)

- Author the per-vector driver for `test_vector_outcome_matches_expected[DV-*]`: materialize each `given` (DV-3 Genesis+cascade-grant; DV-5/7/10 §-invariants; DV-9 Accept), drive a fresh composed `runtime.execute()`, map result → `BehaviouralOutcome`, assert `== expected`.
- Author `test_assert_receipts_agree_across_deterministic_runs` real body (two runs, full vector set).
- Remove the 2 conformance strict-xfail markers on slack.
- **Size**: ≤500 LOC load-bearing, ~5 invariants (one per vector). The spike. If a `given` needs kailash.delegate primitives the connectors don't yet use (R2), surface immediately.
- **Gate**: slack conformance suite green; the driver is a reusable pattern.

### Shards 2–5 — Per-connector application (one each: slack-finish, telegram, whatsapp, email)

Each shard, scoped to ONE connector (disjoint trees → parallelizable, but pin is owned by Shard 0):

- **B** clean un-wire: remove strict-xfail on the compose/e2e tests that XPASS.
- **C** harness fix where needed: telegram compose (socket double); whatsapp compose+e2e (Accept payload — open service window via ingest double or approved-template payload, R1); email compose (double or relocate to mailpit Tier-2).
- **D** exclude_fields: add `audit_head_hash`, `dispatch_result.audit_chain_entries[0]`, `dispatch_result.dispatch_id` to the `*_deterministic` test; re-confirm the exact set against THIS connector's completing run (R4).
- **E** apply the Shard-1 conformance driver pattern; remove the 2 conformance markers.
- **slack** is partly done by Shard 1 (conformance); its shard finishes B+D.
- **Size per shard**: ≤5 invariants, ≤500 LOC. Fits.
- **Gate per shard**: that connector's full suite green on 2.28.1, ZERO xfail remaining on the #1182-gated rows, `--runxfail` clean.

### Shard 6 — email mailpit Tier-2 standup (infra; folds into Shard 5 or standalone)

- Stand up mailpit via `connectors/email/docker-compose.yml`; run the `@requires_mailpit_smtp` e2e + determinism tests for real (R3).
- If mailpit cannot stand up this session → email e2e stays SKIP; flag to user that email's "true end-to-end" is unverified and F2 ships partial for email.

## Definition of done (F2)

- Dev pin + 4 floors on 2.28.x.
- Every #1182-gated strict-xfail removed (16 markers) — replaced by real passing assertions OR (conformance) real per-vector drivers.
- All 4 connector suites green on 2.28.1 with `--runxfail` clean (no silent XPASS).
- `specs/conformance.md` STATUS = ACTIVE; per-vector outcome assertions live.
- mailpit Tier-2 run for email green (or partial-ship flagged to user per R3).
- Regression: a determinism test per connector asserting the 3-field exclude is correct (not over-broad).

## Open questions for the human (carry to /todos gate)

- **R3**: if mailpit won't stand up, ship F2 partial for email (e2e SKIP) or block F2 until email Tier-2 is real?
- Parallelize Shards 2–5 across 4 background agents (disjoint connector trees) vs sequential? Recommend parallel — trees are disjoint, pin is Shard-0-owned.
