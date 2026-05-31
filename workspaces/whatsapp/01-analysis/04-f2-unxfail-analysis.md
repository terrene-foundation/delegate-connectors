# F2 Analysis — Runtime e2e + conformance un-xfail (all 4 connectors)

**Phase**: /analyze · **Date**: 2026-05-31 · **Value-anchor**: #1035 "Delegate
runs end-to-end" + `specs/conformance.md` un-xfail checklist.

Deep evidence + the per-test outcome matrix live in
`workspaces/whatsapp/journal/0008-DISCOVERY-F2-scope-correction-1182-fixed-but-flip-non-uniform.md`.
This doc is the actionable distillation feeding `02-plans/03-f2-shard-plan.md`.

## Brief corrections (gate before /todos)

The F2 brief (journal/0007) was verified claim-by-claim against a live kailash
2.28.1 isolated-venv run with `--runxfail` + transition-reason probes. Four
corrections:

1. **#1182 IS fixed** ✓ — slack compose + slack e2e + telegram e2e all
   XPASS(strict) against the protocol-faithful socket double. Confirmed.
2. **exclude_fields is 3 fields, not 1** — the completing determinism path
   diverges on `audit_head_hash`, `dispatch_result.audit_chain_entries[0]`,
   `dispatch_result.dispatch_id` (all per-run-by-design). journal/0007's
   "1 field" was an artifact of a failing whatsapp payload.
3. **The asymmetry is the test harness, not the connector** — a test flips iff
   it drives a socket double on an Accept path. Non-flips fail for correct
   downstream reasons #1182 previously masked: whatsapp `OutsideServiceWindowError`
   (freeform-no-window Reject), email `SMTPConnectError` (compose "unit" test
   hits real SMTP), telegram compose (real API call, no double).
4. **F2 is 5 work-classes, not "un-wire 16 markers"** (below). mailpit Tier-2 is
   on email's critical path.

## The 5 work-classes

| #   | Class                      | Surface                                                                                                                                          | Nature                                      |
| --- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------- |
| A   | Pin bump                   | 4× `pyproject.toml` floor `>=2.26.1`→`>=2.28.0`; dev/CI pin → 2.28.1                                                                             | boilerplate                                 |
| B   | Clean un-wire              | slack compose, slack e2e, telegram e2e — remove strict-xfail; assertion already holds                                                            | mechanical                                  |
| C   | Harness fix → then un-wire | whatsapp compose+e2e (Accept payload), email compose (double or relocate to mailpit), telegram compose (double)                                  | load-bearing test authoring                 |
| D   | exclude_fields             | 4× `*_deterministic` tests — add the 3 per-run fields                                                                                            | mechanical (email re-checked under mailpit) |
| E   | Conformance bodies         | 8 stub bodies (2 per connector): `test_vector_outcome_matches_expected` (DV-3/5/7/9/10) + `test_assert_receipts_agree_across_deterministic_runs` | **load-bearing — the hard core**            |

Class E is the dense shard: each vector's `given` must be materialized and driven
through a composed `runtime.execute()`, mapping the result to `BehaviouralOutcome`
and asserting `== expected`:

- DV-3 §3 (Reject) — Genesis Record + cascade grant widening Financial dim.
- DV-5 §5 (Reject) — composition-level invariant on §5.
- DV-7 §7 (Reject) — composition-level invariant on §7.
- DV-9 §9 (**Accept**) — the single Accept; well-formed composition.
- DV-10 §10 (Reject) — composition-level invariant on §10.

The vector scenarios are connector-agnostic; only the composed runtime differs.
→ design the driver ONCE (on slack, the clean-flip connector), then replicate.

## Constraints / traps (carried from session notes + this analysis)

- Tests shard per channel: `PYTHONPATH="connectors/<c>/src" .venv/bin/python -m pytest connectors/<c>/tests -q`. Shared `test_*.py` basenames collide on combined collect.
- No worktrees: PYTHONPATH-based imports point at MAIN checkout (no editable install). Parallel agents editing different connectors are fine (disjoint trees); parallel agents must NOT share a pin bump (orchestrator owns `pyproject.toml`).
- `DelegateRuntime` is single-shot (§7 TAOD monotonicity) — each `execute()` needs a fresh composed runtime. The determinism tests already build two.
- Conformance stub bodies (`pytest.fail(...)`) stay XFAIL at ANY kailash version — they flip only when the real driver is authored (NOT by the pin bump).
- `runxfail` is the diagnostic that distinguishes "marker now XPASSes" from "body still fails for a new reason" — use it per test before removing any marker.

## Risk register

- **R1** — Class C whatsapp Accept payload: must open a 24h service window (inbound message via the ingest double) OR use an approved template. Verify the double supports it. Medium.
- **R2** — Class E DV-3 Genesis Record + cascade-grant materialization may need kailash.delegate primitives not yet used by the connectors. Spike on slack first. Medium-high (this is the dense shard).
- **R3** — email mailpit Tier-2: docker-compose present but unproven in this session. If mailpit can't stand up, email's e2e stays SKIP and email's "true end-to-end" is unverified → F2 ships partial for email. Flag to user. Medium.
- **R4** — exclude_fields 3-field set assumed from slack/telegram; re-confirm against each connector's completing run (whatsapp once payload Accepts; email under mailpit). Low.
