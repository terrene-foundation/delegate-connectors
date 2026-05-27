# Todo 08 — Mailpit real-infra integration tests (Tier 2/3)

**Implements:** `specs/test-infrastructure.md` § Tier 2/3
**Type:** Test (real infra, no mocks) · **Capacity:** single shard (~5 invariants)
**Depends:** 06, 07

## Do

- `connectors/email/tests/conftest.py` — session-scoped fixture that starts/waits-for
  the Mailpit container (docker-compose from todo 01), yields SMTP/IMAP coordinates,
  tears down. Skip-with-clear-reason if Docker unavailable (per test-skip-discipline:
  "cannot execute", not "system broken").
- `connectors/email/tests/integration/` — real round-trips:
  - SMTP send via the connector `write` path → assert message arrives via IMAP fetch.
  - `read` path fetches it back → assert `AttestedReadReceipt` verifies.
- `connectors/email/tests/integration/test_e2e.py` — compose `DelegateRuntime`
  (todo 06) → `runtime.execute({...send...})` against real Mailpit → assert the
  `RuntimeExecutionResult` carries a verifiable `SignedActionEnvelope`; assert
  `assert_receipts_agree(r1.to_dict(), r2.to_dict())` for two identical runs.

## Invariants (5)

1. NO mocks at the boundary — real Mailpit SMTP+IMAP, real in-memory audit, real
   `Ed25519Verifier`.
2. Send→receive round-trip actually transits Mailpit (assert via IMAP, not internal state).
3. Audit receipt from `execute` verifies under the verifier.
4. Receipt determinism: two identical runs agree (`assert_receipts_agree`).
5. Credentials from env/compose, never hardcoded.

## Acceptance

- [ ] `docker compose up -d mailpit && pytest connectors/email/tests/integration -q` green.
- [ ] e2e proves end-to-end: connector → runtime → real SMTP/IMAP → verifiable receipt.
