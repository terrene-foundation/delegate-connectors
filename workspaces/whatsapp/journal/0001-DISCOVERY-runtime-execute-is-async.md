# DISCOVERY 0001 — runtime.execute() is async (corrects email synthesis "sync")

Date: 2026-05-27
Phase: /analyze (whatsapp)

## Finding

The brief's ADR-2 directive asked to confirm the CURRENT `runtime.execute()`
signature + sync-vs-async by introspecting the wheel, and to note any
discrepancy. There is one.

- `workspaces/email/01-analysis/00-synthesis.md` ADR-2 states `runtime.execute()`
  is **sync** ("not run(), not async").
- `specs/runtime-composition.md` (corrected in PR #5) states it is **async**
  ("`async runtime.execute(...) -> RuntimeExecutionResult` — coroutine; callers
  MUST `await` it").

## Ground truth (introspection, kailash 2.26.2, repo-local venv)

```
inspect.iscoroutinefunction(DelegateRuntime.execute)  -> True
DelegateRuntime.execute signature: (self, input_payload: dict[str, Any]) -> RuntimeExecutionResult
```

## Verdict

`runtime.execute()` IS a coroutine (async). The corrected spec
(`runtime-composition.md`, PR #5) is RIGHT; the email synthesis "sync" line is
STALE. The WhatsApp connector and its e2e harness MUST `await runtime.execute(...)`.

## Disposition

Recorded as a brief correction in `02-plans/01-architecture.md` § Brief
corrections and in `01-analysis/03-connector-contract-mapping.md` Correction 2.
Not propagating the stale "sync" claim. No code in this repo to fix at /analyze
time; the correction binds /implement.
