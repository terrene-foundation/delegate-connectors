# Todo 06 — Tier-1 unit tests

**Implements:** `specs/test-infrastructure.md` § Tier 1
(+ `02-plans/02-connector-spec.md` § Transport + § Principal resolution)
**Type:** Test (feedback-loop shard) · **Capacity:** single shard (boilerplate-heavy; may exceed base LOC)
**Depends:** 02–05

## Do

- `connectors/telegram/tests/unit/` — pure-Python, no I/O, offline. Cover:
  - Transport: `OutboundMessage` construction validation (control-char reject, ≤ 4096
    UTF-16 length bound, `chat_id` shape), `429`→typed rate-limit error (todo 02).
  - Directory: dual-keyed resolution (known `user_id` → Principal; `chat_id` → same
    Principal), unknown → `Reject`, `@handle` → `Reject` (todo 03).
  - Connector: ABC compliance (`isinstance`), read/write return non-empty verifiable
    receipts, trust properties return concretes (todo 04).
  - Compose: `build_telegram_runtime` builds a runtime; `await execute` returns a
    `RuntimeExecutionResult` with a signed envelope (thunk stubbed at the SDK boundary
    only — todo 05).
- The external thunk boundary is the ONLY thing stubbed at Tier-1 (the `httpx` Bot API
  call); the `Connector`/runtime contract itself is NEVER mocked.

## Acceptance

- [ ] `../../.venv/bin/python -m pytest connectors/telegram/tests/unit -q` green.
- [ ] No mocks of the `Connector`/runtime contract itself (only the external Bot API
      thunk boundary is stubbed at Tier-1).
- [ ] Coverage includes the unknown-sender `Reject` path explicitly.
- [ ] Coverage includes the construction-validation reject path explicitly.
