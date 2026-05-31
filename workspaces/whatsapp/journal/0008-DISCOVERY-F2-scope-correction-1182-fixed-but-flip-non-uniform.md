# 0008 — DISCOVERY: F2 scope correction — #1182 fixed, but the per-connector xfail flip is NON-uniform

**Type**: DISCOVERY
**Date**: 2026-05-31
**Phase**: /analyze (F2)
**Evidence**: isolated-venv run of all 4 suites against kailash **2.28.1** with
`--runxfail` + direct `runtime.execute()` probes capturing the taod transition
`reason` (NOT just xfail counts). Venv: `/tmp/f2-verify-venv` (kailash 2.28.1 +
cryptography/httpx/aiosmtplib/aiohttp/aioimaplib/slack_sdk). Dev pin stays 2.26.2.

## Why this entry exists

journal/0007 unblocked F2 from an xfail-**count** delta (slack/telegram/whatsapp
dropped to 6/7/8 xfails; email unchanged at 7) and framed the asymmetry as
"email wires its execute() gating differently." Re-verifying every brief claim
with `--runxfail` + transition-reason probes (per `rules/agents.md` § Parallel
Brief-Claim Verification, ≥3-issue brief) shows the count delta was real but the
**root-cause framing was wrong**. F2 is NOT a mechanical "remove 16 xfail
markers." Four corrections below.

## Confirmed: #1182 IS fixed at ≤2.28.1

The runtime audit-emit signature bug (signs payload bytes; `AuditChainEngine`
verifies full-entry bytes → `execute()` failed at the FIRST phase transition
`thinking→acting` under any real verifier) is fixed. Authoritative receipts:

- slack `unit/test_compose.py::test_runtime_execute_end_to_end_gated_on_sdk_fix` → **XPASS(strict)** (execute() completes).
- slack `integration/test_e2e.py::test_runtime_execute_e2e_against_double_completes` → **XPASS(strict)** (completes against the protocol-faithful socket double).
- telegram `integration/test_e2e.py::…_against_double_completes` → **XPASS(strict)**.

At 2.28.1 `execute()` now PROCEEDS to the `acting` phase and dispatches. The
phase=="failed" cases below are dispatch-phase **domain/infra** failures that
#1182 previously **masked** by short-circuiting before dispatch ever fired.

## Per-test outcome matrix @ kailash 2.28.1

| Connector | compose `*_gated_on_sdk_fix`               | e2e `*_completes`            | e2e `*_deterministic`        | conformance (2 stubs) |
| --------- | ------------------------------------------ | ---------------------------- | ---------------------------- | --------------------- |
| slack     | **XPASS** (clean flip)                     | **XPASS** (clean)            | FAIL — 3 fields              | XFAIL (stub bodies)   |
| telegram  | XFAIL — `dispatch raised` (API, no double) | **XPASS** (clean)            | FAIL — 3 fields              | XFAIL (stub bodies)   |
| whatsapp  | XFAIL — `OutsideServiceWindowError`        | XFAIL — same domain Reject   | FAIL — 1 field\*             | XFAIL (stub bodies)   |
| email     | XFAIL — `SMTPConnectError`                 | SKIPPED (`requires_mailpit`) | SKIPPED (`requires_mailpit`) | XFAIL (stub bodies)   |

\* whatsapp determinism diverged on only `audit_head_hash` because BOTH runs
fail identically (service-window Reject) → `dispatch_result` is absent/equal;
once the payload Accepts, it will diverge on the same 3 fields as slack/telegram.

## Correction 1 — exclude_fields is 3 fields, not 1

journal/0007 said "add `audit_head_hash`." The completing path (slack/telegram
`*_deterministic`) actually diverges on **3** per-run-by-design fields:
`audit_head_hash`, `dispatch_result.audit_chain_entries[0]`,
`dispatch_result.dispatch_id`. Current `exclude_fields={"run_id","at"}` →
`ReceiptsAgreementError`. The "1 field" whatsapp reading was an artifact of its
failing payload (above). Exact set to be re-confirmed against a completing run
at /implement, but the floor is these 3.

## Correction 2 — the asymmetry is the TEST HARNESS, not the connector

journal/0007: "email wires execute() differently." Reality: a test flips
cleanly **iff it drives a protocol-faithful socket double on an Accept path**.
Non-flips are NOT #1182 residue and NOT connector bugs — they are correct
behavior the test payload/infra triggers:

- **whatsapp** compose+e2e: `OutsideServiceWindowError` — freeform `{"text":"hi"}`
  with no open 24h window is a CORRECT Reject. Test payload must Accept (approved
  template, or an inbound message opening the service window).
- **email** compose `*_gated`: `SMTPConnectError` — a "unit" test that reaches
  dispatch against a real SMTP transport with no server. The real Tier-2 mailpit
  e2e test exists but is SKIPPED (no mailpit running here).
- **telegram** compose `*_gated`: real Telegram API dispatch failure — its
  socket-double e2e test DOES XPASS, so execute() completes with proper infra.

## Correction 3 — F2 is 5 work-classes, not "un-wire 16 markers"

1. **Pin bump**: floor `kailash>=2.26.1` → `>=2.28.0` (×4 pyproject); dev/CI pin → 2.28.1.
2. **Clean un-wires** (assertion already holds): slack compose, slack e2e, telegram e2e — remove strict-xfail markers.
3. **Test-harness fixes** (make the send Accept, then un-wire): whatsapp compose+e2e (template/service-window payload), email compose (socket double or relocate to mailpit Tier-2), telegram compose (socket double). These are TEST authoring, not connector changes.
4. **exclude_fields fix** on the 4 `*_deterministic` tests (3 fields; email re-checked under mailpit).
5. **Author 8 conformance bodies** (2 per connector × 4): `test_vector_outcome_matches_expected` (5 vectors DV-3/5/7/9/10) + `test_assert_receipts_agree_across_deterministic_runs` — currently stub bodies (`pytest.fail(...)`) that stay XFAIL at ANY kailash version; they only flip when the real per-vector driver is written.

## Correction 4 — mailpit/Tier-2 infra is on the F2 critical path for email

email's `*_completes` + `*_deterministic` are `@requires_mailpit_smtp` and SKIP
without it. F2 "true end-to-end for all 4 connectors" therefore requires standing
up mailpit (docker-compose.yml present in connectors/email/) — otherwise email's
end-to-end claim is unverified. Same likely applies to slack/telegram/whatsapp
live Tier-3 (out of F2 scope per F6; the socket doubles are the F2 surface).

## Disposition

F2 proceeds, but the plan is the 5 work-classes above, sharded per connector +
work-class (see 01-analysis architecture doc). The "un-wire 16 markers" framing
is retired. The #1182-fixed receipt is the two slack XPASS rows + the telegram
e2e XPASS row above — durable, runtime-sourced (verify-resource-existence MUST-2).
