# 0011 — GAP: runtime-composition spec claimed `execute()` synchronous; shipped SDK is async

**Type:** GAP (spec-accuracy)
**Date:** 2026-05-27
**Phase:** /redteam re-validation (Round 1)
**Status:** FIXED this round (spec corrected); code was already correct.

## Finding

`specs/runtime-composition.md` asserted `runtime.execute()` is **synchronous** in two
places:

- `:32` — `# 5. execute — SYNC, returns RuntimeExecutionResult` with
  `result = runtime.execute(input_payload={...})` (no `await`)
- `:38` — `` `runtime.execute(input_payload: dict) -> RuntimeExecutionResult` — synchronous. ``

The shipped SDK contradicts this. Verified against kailash 2.26.2:

```
$ python -c "import inspect; from kailash.delegate import DelegateRuntime; \
             print(inspect.iscoroutinefunction(DelegateRuntime.execute))"
True
```

`DelegateRuntime.execute` is a **coroutine** — callers MUST `await` it. The connector
code and every test already await it correctly (`compose.py:109` docstring,
`tests/unit/test_compose.py:95`, `tests/integration/test_e2e.py:58,87,88`), so this was
a **spec-vs-shipped-API divergence with no logged deviation**, not a code bug.

## Severity

MEDIUM. The code path is correct and all tests pass; the defect was confined to the
domain-truth surface. Left uncorrected it is a lookaway trap: a downstream connector
author reading `specs/runtime-composition.md` would write `result = runtime.execute(...)`
(no await), receive a coroutine object instead of a `RuntimeExecutionResult`, and the
send would silently never fire. This is exactly the `spec-accuracy.md` MUST-1 failure mode
(a contract citation that does not resolve against working code).

## Fix

`specs/runtime-composition.md:32-39` corrected to describe the async coroutine contract
and pin the verification (`inspect.iscoroutinefunction(...) is True`, kailash 2.26.2).
Per `specs-authority.md` Rule 5b the edit triggered a full sibling-spec re-derivation
(Round 2): no other spec carried a residual `synchronous`-execute claim; all spec-cited
SDK symbols still resolve; `Connector.__abstractmethods__` is still exactly the 7 members.

## Cross-references

- `specs/runtime-composition.md` (corrected)
- `rules/spec-accuracy.md` MUST-1, `rules/specs-authority.md` Rule 5b/6
- Distinct from the SDK `execute()` audit-signature bug (journal 0005 / kailash-py#1182):
  that is a runtime _behavior_ bug (execute returns `phase=="failed"` under a real
  verifier); this is a spec _accuracy_ defect about execute's _call shape_ (async vs sync).
  Both touch `execute()` but are independent.
