# Todo 06 — Wire connector into DelegateRuntime (end-to-end)

**Implements:** `specs/runtime-composition.md`
**Type:** WIRE (real data end-to-end) · **Capacity:** single shard (~150 LOC, 4 invariants)
**Depends:** 05

## Do

- `src/delegate_connectors/email/compose.py` — a helper that composes a runnable
  `DelegateRuntime` around an `EmailConnector`: build `PrincipalDirectory` +
  `Ed25519Verifier`, in-memory `AuditChainEngine`, `DispatchSurface(connector,
signature, envelope, identity, audit_engine=…, trust_cascade=…, role=…, signer=…,
verifier=…)`, then `DelegateRuntime(...)`.
- Provide a minimal v0 fixture `signature` (application-supplied; documented as a
  v0 placeholder, not a stub-for-production).
- Entry: `runtime.execute(payload) -> RuntimeExecutionResult`.

## Invariants (4)

1. Uses real shipped concretes for audit/verifier/cascade — no mocks.
2. `runtime.execute(...)` returns a `RuntimeExecutionResult` whose audit chain
   carries the connector's signed write envelope.
3. Envelope passed in is honored (tightening preserved).
4. The composed runtime is reusable (no per-call global state).

## Acceptance

- [ ] `runtime.execute({...send...})` produces a `RuntimeExecutionResult` with a
      verifiable `SignedActionEnvelope` in the chain (Tier-1 with thunk; Tier-2 in todo 08).
- [ ] `result.to_dict()` is stable across two identical runs (feeds `assert_receipts_agree`).
