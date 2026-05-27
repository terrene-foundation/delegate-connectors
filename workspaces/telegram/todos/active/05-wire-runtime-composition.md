# Todo 05 — Wire connector into DelegateRuntime (end-to-end)

**Implements:** `specs/runtime-composition.md`
(+ `02-plans/02-connector-spec.md` § Responsibilities — `invoke` dispatch path)
**Type:** WIRE (real data end-to-end) · **Capacity:** single shard (~250 LOC, 4 invariants)
**Depends:** 04

## Do

- `src/delegate_connectors/telegram/compose.py` — `build_telegram_runtime(...)` that
  composes a runnable `DelegateRuntime` around a `TelegramConnector` via direct
  construction (the `Delegate.compose(...)`/`pact_engine=` shape does NOT exist):
  build `PrincipalDirectory` + `Ed25519Verifier`, in-memory `AuditChainEngine` over a
  `TrustLineageChain`, `TenantScopedCascade`, `Role`, a real Ed25519 `signer`, a
  `DispatchSurface(connector, signature, envelope, identity, audit_engine=…,
trust_cascade=…, role=…, signer=…, verifier=…)`, then `DelegateRuntime(...)`.
- Provide a minimal v0 fixture `signature` (application-supplied; documented as a v0
  placeholder, not a stub-for-production).
- Entry: `await runtime.execute(input_payload)` — `execute` is an async coroutine
  (journal/0002, `specs/runtime-composition.md`); callers MUST `await` it. No
  `asyncio.run()` bridge inside the thunk (consistent async-ness).

## Invariants (4)

1. Uses real shipped concretes for audit/verifier/cascade — `Ed25519Verifier`, NOT
   `NullVerifier`; in-memory `AuditChainEngine`, NO Postgres, NO PACT container.
2. `await runtime.execute(...)` returns a `RuntimeExecutionResult` whose audit chain
   carries the connector's signed write envelope.
3. Envelope monotonic-tightening honored (widening raises `EnvelopeWideningError`).
4. The composed runtime is reusable — no per-call global state.

## Acceptance

- [ ] `await runtime.execute({...send...})` produces a `RuntimeExecutionResult` with a
      verifiable `SignedActionEnvelope` in the chain (Tier-1 with thunk; real-infra in todo 07).
- [ ] `result.to_dict()` is stable across two identical runs (feeds `assert_receipts_agree`).
- [ ] `build_telegram_runtime(...)` returns populated handles (runtime, connector,
      verifier, identity) — the conformance composition precondition (todo 08).
