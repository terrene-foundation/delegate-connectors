---
type: DISCOVERY
date: 2026-05-27
created_at: 2026-05-27T00:05:00Z
author: agent
session_id: telegram-connector-analyze
session_turn: 4
project: telegram-connector
topic: runtime.execute() re-confirmed async against the wheel; email synthesis line 30 ("sync") is stale, shared runtime-composition spec is correct
phase: analyze
tags: [sdk-constraint, runtime, async, spec-staleness, grounding]
---

# DISCOVERY — execute() is async (re-confirmed); email synthesis is stale

## Finding (kailash 2.26.2)

Re-introspecting the wheel to ground the Telegram spec's runtime contract:

```
$ .venv/bin/python -c "import inspect; from kailash.delegate import DelegateRuntime; \
                       print(inspect.iscoroutinefunction(DelegateRuntime.execute))"
True
```

`DelegateRuntime.execute(self, input_payload: dict[str, Any]) -> RuntimeExecutionResult`
is a coroutine — callers MUST `await` it.

Two repo surfaces disagree:

| Source                                            | Claim | Verdict |
| ------------------------------------------------- | ----- | ------- |
| `specs/runtime-composition.md:38` (PR #5)         | async | CORRECT |
| `workspaces/email/01-analysis/00-synthesis.md:30` | sync  | STALE   |

The shared `specs/runtime-composition.md` is correct (corrected in PR #5; email's
own `journal/0011-GAP-*` records the fix). The email SYNTHESIS doc was not
back-patched and still reads "sync."

## Consequence

The Telegram spec + plan cite the async contract from
`specs/runtime-composition.md`, NOT the stale email synthesis line. This is a
cross-workspace staleness note, not a blocker — the Telegram connector inherits
the async-await call shape email's CODE already uses correctly. The stale email
synthesis line is outside this workspace's write scope; flagged for the
orchestrator's cross-workspace reconciliation.

## For Discussion

1. A Telegram-connector author reading the email synthesis first (it is the
   gold-standard depth reference) could copy the "sync" claim. Does the stale line
   become a lookaway trap, or does `specs/runtime-composition.md` reliably override?
2. Had `execute()` been sync, would the HTTP transport (inherently async via
   `httpx`) have forced an `asyncio.run()` bridge inside the thunk — violating
   `rules/patterns.md` § Consistent Async-ness?
3. Both inherited blockers (#1182, #1035) and this staleness note are
   runtime/spec issues, not transport issues. Are these properly shared-spec
   residuals every future channel inherits, rather than per-channel findings?
