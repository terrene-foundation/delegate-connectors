# Todo 10 — Tier-2 local Cloud API double + Tier-3 live e2e

**Implements:** `specs/test-infrastructure.md` § Tier 2/3 (+ `02-plans/02-connector-spec.md` § Transport, WA-ADR-5; journal 0003 Gap A)
**Type:** Test (real-infra surrogate, no mocks) · **Capacity:** single shard (~5 invariants)
**Depends:** 08, 09

**Value-anchor:** delivers the brief acceptance criteria "Outbound message send … verified to arrive (real-infra check, not a mocked client). Sandbox account acceptable for v0 e2e" and "Tier-2/3 real-infra suite green" — via a protocol-faithful local double (no vendor coupling) with the live Meta sandbox as opt-in Tier-3.

## Do

- `connectors/whatsapp/tests/conftest.py` — fixture providing the in-process
  protocol-faithful Cloud API double: an `httpx`-compatible responder (a Protocol-satisfying
  deterministic adapter, NOT a mock per `rules/testing.md` § Tier 3 exception) that speaks the
  Meta `POST /messages` request/response shape and accepts an inbound-webhook injection helper.
- `connectors/whatsapp/tests/integration/` — real round-trips against the double:
  - Send via the connector `write` path → assert the request shape Meta would receive +
    `SendResult` carries `wamid` + `wa_id`.
  - Inject a signed inbound webhook → buffer → `read` path → assert a verifiable
    `AttestedReadReceipt`.
- `connectors/whatsapp/tests/integration/test_e2e.py` — compose `DelegateRuntime` (todo 08) →
  `await runtime.execute({...send...})` against the double → assert the
  `RuntimeExecutionResult` carries a verifiable `SignedActionEnvelope`; assert
  `assert_receipts_agree(r1.to_dict(), r2.to_dict())` for two identical runs. The end-to-end
  outcome assertion is **strict-xfail** pending kailash-py#1182.
- Tier-3 live: a single opt-in `test_live_meta_sandbox` gated on real `WHATSAPP_*`
  credentials; skipped with a "cannot execute" reason when absent (journal 0003 Gap A) — never
  a mock fallback.

## Invariants (5)

1. NO mocks at the boundary — the local double is a Protocol-satisfying deterministic adapter;
   real in-memory audit, real `Ed25519Verifier`.
2. Send path asserts the request the double receives matches the Meta `POST /messages` contract.
3. Inbound: signed-webhook → buffer → `read` → `AttestedReadReceipt` verifies under the verifier.
4. Receipt determinism: two identical runs agree (`assert_receipts_agree`).
5. Credentials from env / fixture, never hardcoded; Tier-3 skip is "cannot execute", not a mock.

## Acceptance

- [ ] `../../.venv/bin/pytest connectors/whatsapp/tests/integration -q` green (Tier-2 against
      the local double; the e2e outcome row strict-xfail per #1182).
- [ ] Tier-3 `test_live_meta_sandbox` skips cleanly with a "cannot execute" reason when no live
      `WHATSAPP_*` creds are present; runs (and asks Meta sandbox) only when they are.
- [ ] No aggregator SDK present in the test tree (WA-ADR-1 / WA-ADR-5).
