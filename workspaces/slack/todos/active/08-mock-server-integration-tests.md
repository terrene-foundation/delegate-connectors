# Todo 08 — Web API mock-server integration (Tier 2/3)

**Implements:** `specs/test-infrastructure.md` § Tier 2/3 (+ `02-plans/02-connector-spec.md` § Transport; ADR-S4 per `01-analysis/00-synthesis.md`)
**Type:** Test (real boundary, no connector-boundary mocks) · **Capacity:** single shard (~3 invariants + infra)
**Depends:** 06, 07

## Do

- `connectors/slack/docker-compose.yml` — ONE Web API mock-server service serving the
  two methods v0 uses: `chat.postMessage` (records the post, returns a `ts`) and
  `conversations.history` (replays the recorded messages). WireMock/Prism-seeded or a
  small purpose-built stub. This is the local server stub (exactly as Mailpit is a
  local SMTP server) — the connector talks to it via a REAL
  `AsyncWebClient(base_url=…)`; there is NO mocking at the connector boundary. The
  stale Node `slack-mock` is NOT used (unmaintained — `01-analysis/00-synthesis.md`).
- `connectors/slack/tests/integration/_slack_mock.py` — reachability gate
  `requires_slack_mock` that skips with a clear "cannot execute" reason when the
  container is not reachable (per test-skip discipline: "cannot execute", not
  "system broken").
- `connectors/slack/tests/integration/` — real round-trip:
  - post via the connector `write`/`invoke` path → assert the message is recorded
    at the mock (verified through `conversations.history`, not internal state).
  - `read` path pulls it back through the connector → assert the
    `AttestedReadReceipt` verifies under the real `Ed25519Verifier`.
- `connectors/slack/tests/integration/test_e2e.py` — compose a `DelegateRuntime`
  (todo 06) → `await runtime.execute({...post...})` against the mock container →
  assert the result carries a verifiable `SignedActionEnvelope`, and
  `assert_receipts_agree(r1.to_dict(), r2.to_dict())` for two identical runs. The
  end-to-end `execute()` OUTCOME assertion is strict-xfail per todo 09 (kailash-py#1182).
- Tier-3 (opt-in, NOT default CI): a live-workspace round-trip behind a
  `requires_live_slack` skip-gate + test bot token (mirrors email's
  `requires_greenmail`).

## Invariants (3)

1. NO mocks at the connector boundary — a real `AsyncWebClient` against the mock
   server, real in-memory audit, real `Ed25519Verifier`.
2. The post→history round-trip actually transits the mock server (assert via
   `conversations.history`, not internal connector state).
3. The `AttestedReadReceipt` from the round-trip verifies under the verifier.

## Acceptance

- [ ] `docker compose -f connectors/slack/docker-compose.yml config` validates.
- [ ] With the container up:
      `../../.venv/bin/pytest connectors/slack/tests/integration -q` green
      (skips cleanly with a "cannot execute" reason when the container is down).
- [ ] The round-trip proves: connector → real `AsyncWebClient` → mock server →
      verifiable identity-bound receipt.
