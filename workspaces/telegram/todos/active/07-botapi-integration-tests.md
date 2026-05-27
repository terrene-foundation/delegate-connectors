# Todo 07 — Local Bot API real-infra integration tests (Tier 2/3)

**Implements:** `specs/test-infrastructure.md` § Tier 2/3
(+ `02-plans/02-connector-spec.md` § Transport)
**Type:** Test (real infra, no mocks; feedback-loop shard) · **Capacity:** single shard (~5 invariants)
**Depends:** 05, 06

## Do

- `connectors/telegram/tests/conftest.py` — session-scoped fixture that starts/waits-for
  the local Bot API HTTP service (docker-compose from todo 01; a hermetic surrogate
  implementing `sendMessage` + `getUpdates` over a real socket + JSON cycle — ADR-T4),
  yields its coordinates, tears down. Skip-with-clear-reason if Docker/service is
  unreachable (per test-skip discipline: "cannot execute", not "system broken").
- `connectors/telegram/tests/integration/_botapi.py` — reachability gate
  (`requires_botapi`) skipping with a "cannot execute" reason when the service is down.
  Optional secret-gated live-bot path (skipped by default — ADR-T4).
- `connectors/telegram/tests/integration/` — real round-trips against the surrogate:
  - Outbound: send via the connector `write` path → assert the message arrives at the
    destination chat (assert via the service's delivered-message surface, NOT internal state).
  - Inbound: `read` path long-polls `getUpdates` → assert a verifiable, identity-bound
    `AttestedReadReceipt`.
- `connectors/telegram/tests/integration/test_e2e.py` — compose a `DelegateRuntime`
  (todo 05) → `await runtime.execute({...send...})` against the real surrogate → assert
  the `RuntimeExecutionResult` carries a verifiable `SignedActionEnvelope`; assert
  `assert_receipts_agree(r1.to_dict(), r2.to_dict())` for two identical runs. The
  end-to-end `runtime.execute()` outcome is `xfail`-strict gated on kailash-py#1182
  (audit-emit signs payload bytes while `AuditChainEngine` verifies the full entry
  signing bytes — journal/0002 references the shared inherited blocker).

## Invariants (5)

1. NO mocks at the boundary — real local Bot API service (real socket), real in-memory
   `AuditChainEngine`, real `Ed25519Verifier`.
2. Outbound send actually transits the surrogate (assert via its delivered-message
   surface, not connector internal state).
3. Inbound `read` receipt verifies under the shipped `Ed25519Verifier`.
4. Receipt determinism: two identical runs agree (`assert_receipts_agree`).
5. Credentials from env/compose, never hardcoded; token/URL never logged.

## Acceptance

- [ ] `docker compose -f connectors/telegram/docker-compose.yml up -d` then
      `../../.venv/bin/python -m pytest connectors/telegram/tests/integration -q` green
      (the `runtime.execute()` e2e outcome assertion `xfail`-strict on #1182).
- [ ] Outbound arrival proven via the surrogate's delivered surface.
- [ ] Inbound round-trip yields an `AttestedReadReceipt` verifying under the real verifier.
