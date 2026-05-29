# GAP — Conformance per-vector strict-xfail bodies cannot auto-flip to XPASS

**Type:** GAP
**Surfaced:** 2026-05-29, WhatsApp Wave-3 `/redteam` Round 2 (fresh-context re-derivation)
**Severity:** LOW
**Scope:** cross-connector (email + whatsapp — the only two connectors with conformance harnesses)
**Disposition:** documented + recommended; NOT fixed in WhatsApp in isolation (would diverge from the email template that todo 11 mandated mirroring).

## The gap

The two conformance per-vector strict-xfail bodies —
`connectors/whatsapp/tests/conformance/test_canonical_set.py`:

- `test_vector_outcome_matches_expected` (parametrized ×5, lines ~188-208)
- `test_assert_receipts_agree_across_deterministic_runs` (lines ~224-240)

raise a hardcoded `AssertionError` and **never invoke `runtime.execute()`**. The
docstrings (and the module docstring §2) claim that when kailash-py#1182 is
fixed, these strict-xfails "flip to XPASS and FAIL the suite by design," forcing
the marker's removal + per-vector wiring. Because the body raises
unconditionally and never touches the `#1182`-gated path, fixing #1182 will
**not** make them XPASS — the strict-xfail stays red and the forcing function
never fires.

Contrast the sibling unit/integration xfails, which DO drive the gated path and
WILL flip correctly:

- `tests/unit/test_compose.py::test_runtime_execute_end_to_end_gated_on_sdk_fix`
  — `await composed.runtime.execute(...)` then `assert phase == "completed"`.
- `tests/integration/test_e2e.py::...` — same, against the Cloud-API double.

## Why this is inherited, not a Wave-3 defect

The pattern is byte-identical in the email connector's conformance harness
(`connectors/email/tests/conformance/test_canonical_set.py:171` — same bare
`raise AssertionError` + the same "records intent without faking a result"
comment). Todo 11 explicitly directed the WhatsApp harness to "mirror email's
half-active treatment." So this is a deliberate, established, previously-converged
template pattern — the per-vector scenario wiring (mapping each vector's `given`
to a runtime drive against the Cloud-API double) was intentionally deferred to
the "un-xfail shard" that lands when #1182 ships. The forcing function in the
email design is the planned un-xfail work item, not an automatic XPASS flip.

## Why NOT fixed here

1. **Mirror-consistency:** rewriting only WhatsApp's bodies to drive `execute()`
   would diverge it from email (and any future connector), breaking the
   cross-connector conformance-harness symmetry todo 11 mandated.
2. **Scope:** the correct fix is template-wide (email + whatsapp), touching the
   shipped, already-converged email connector — scope expansion beyond the
   WhatsApp Wave-3 brief (`/autonomize` Prudence → surface + confirm, do not
   self-authorize).
3. **Severity:** LOW. It does not produce a false green, hide a security gap, or
   weaken any shipped assertion. The suite is correctly red/xfail today; the 5
   well-formedness + composition rows that run today all pass.

## Recommendation (for user decision)

Template-wide improvement: make the per-vector conformance xfail bodies in BOTH
email and whatsapp drive `composed.runtime.execute()` against the Cloud-API
double (asserting `phase == "completed"`, the #1182 symptom), so the strict-xfail
becomes genuinely #1182-gated and flips to XPASS when the SDK fix lands — turning
the forcing function real while keeping the per-vector `given`→outcome mapping
deferred. Tracked as a follow-up; pairs with the existing #1182 un-xfail shard
(F2 in the forest ledger) that already must rewrite these bodies when the SDK
fix ships.

## Cross-references

- F2 (forest ledger): "Runtime e2e + conformance per-vector un-xfail" — BLOCKED on
  kailash-py#1182. This GAP refines F2: when F2 is actioned, fix the forcing-
  function shape in both connectors, not just remove markers.
- `compose.py` § KNOWN SDK BLOCKER (kailash-py#1182).
- `specs/conformance.md` § When unblocked.
