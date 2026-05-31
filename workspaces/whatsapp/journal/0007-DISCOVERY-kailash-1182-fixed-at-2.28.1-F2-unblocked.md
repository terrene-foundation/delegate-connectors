# 0007 — DISCOVERY: kailash-py#1182 fixed at ≤2.28.1; F2 (e2e + un-xfail) unblocked

**Type**: DISCOVERY
**Date**: 2026-05-31
**Evidence**: isolated-venv run of all 4 suites against kailash 2.28.1 (runtime, not issue tracker)

## What changed

The forest-ledger F2 row ("Runtime e2e + conformance per-vector un-xfail, all 4
connectors") was BLOCKED on kailash-py#1182 — the runtime/dispatch audit-emit
signed the event PAYLOAD bytes while `AuditChainEngine` verified the FULL
audit-entry bytes, so `runtime.execute()` returned `phase=="failed"` under any
real verifier. The connectors encoded this as **strict** xfails (the forcing
function: XPASS→FAIL when the SDK fix lands).

Running the suites against **kailash 2.28.1** (dev pin is 2.26.2), those strict
xfails now `[XPASS(strict)]` → fail:

- slack `test_runtime_execute_end_to_end_gated_on_sdk_fix` — XPASS(strict).
  `runtime.execute()` now SUCCEEDS end-to-end. **#1182 is fixed at ≤2.28.1.**
- slack/telegram/whatsapp `test_runtime_execute_*_deterministic_across_two_runs`
  now actually execute (previously couldn't) and reveal one real wiring gap:
  `assert_receipts_agree` disagrees on `audit_head_hash` across two runs — the
  audit chain head commits per-run data (timestamps / chain state), so this
  field is non-deterministic BY DESIGN and must be added to the test's
  `exclude_fields` (alongside `run_id`) when the xfail is un-wired.

## Compatibility verdict (connector-level)

The connectors are connector-level COMPATIBLE with 2.28.1: all send / read /
sign / verify / redaction / HMAC / reject-before-sign tests pass
(email 59, slack 101, telegram 113, whatsapp 129). The only failures are the
`runtime.execute()` rows whose behavior changed because the SDK gate lifted —
NOT incompatibilities. (kailash 2.27.0+ also loosened the `Connector` ABC to a
single abstract `invoke`; the connectors implement a superset, so still
compatible.)

Asymmetry to note: email's #1182-gated rows did NOT flip on 2.28.1 (7 xfailed
unchanged) while slack/telegram/whatsapp dropped to 6/7/8 — email (oldest
connector) wires its execute() gating differently and needs its own check when
F2 is taken up.

## F2 disposition (now ACTIONABLE — user decision)

Two paths, for the user:

- **(a) Ship v0 now on the 2.26.2 pin** — suites green, #1182-gated rows stay
  strict-xfail by design at 2.26.2. F2 becomes a follow-up when the pin moves.
- **(b) Take F2 now** — move dev pin to 2.28.1, un-wire the strict-xfails to
  real assertions, fix the deterministic test `exclude_fields` (add
  `audit_head_hash`), reach true end-to-end (delivers #1035 "Delegate runs
  end-to-end"). Bigger work; re-check email's gating separately.

Value-anchor: F2 = #1035 "Delegate runs end-to-end" + `specs/conformance.md`
un-xfail checklist. The blocker that justified its deferral has lifted.

## Scope note

#1182 fix confirmed via RUNTIME (the XPASS), not via a cross-repo `gh` read of
the issue (out of scope per repo-scope-discipline; the live runtime result is
the authoritative evidence per verify-resource-existence MUST-2).
