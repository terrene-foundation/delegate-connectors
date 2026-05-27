# Todo 08 — Wire connector into DelegateRuntime (end-to-end)

**Implements:** `specs/runtime-composition.md` (+ `02-plans/02-connector-spec.md` § Responsibilities (`invoke`); brief correction "`runtime.execute()` is ASYNC")
**Type:** WIRE (real composition, real data) · **Capacity:** single shard (~150 LOC, 4 invariants)
**Depends:** 07

**Value-anchor:** delivers the brief acceptance criterion "Outbound message send … verified to arrive at the destination phone number (real-infra check, not a mocked client)" by composing the connector into a runnable `DelegateRuntime` — the end-to-end path the brief's e2e check exercises.

## Do

- `src/delegate_connectors/whatsapp/compose.py` — a helper that composes a runnable
  `DelegateRuntime` around a `WhatsAppConnector`: build `PrincipalDirectory` +
  `Ed25519Verifier`, in-memory `AuditChainEngine`, `DispatchSurface(connector, signature,
envelope, identity, audit_engine=…, trust_cascade=…, role=…, signer=…, verifier=…)`,
  then `DelegateRuntime(...)` with `posture="L5_DELEGATED"`.
- Provide a minimal v0 fixture `signature` (application-supplied; documented as a v0
  placeholder, not a stub-for-production).
- Entry: `await runtime.execute(input_payload={...}) -> RuntimeExecutionResult`
  (`runtime.execute` is an async coroutine — callers MUST `await`; journal 0001).

## Invariants (4)

1. Uses real shipped concretes for audit / verifier / cascade — no mocks.
2. `await runtime.execute(...)` returns a `RuntimeExecutionResult` whose audit chain carries
   the connector's signed write envelope.
3. Envelope monotonic-tightening honored (widening raises `EnvelopeWideningError`).
4. The composed runtime is reusable (no per-call global state).

## Acceptance

- [ ] `await runtime.execute({...send...})` produces a `RuntimeExecutionResult` with a
      verifiable `SignedActionEnvelope` in the chain (Tier-1 with thunk against the local
      double; Tier-2 in todo 10).
- [ ] `result.to_dict()` is stable across two identical runs (feeds `assert_receipts_agree`).
- [ ] The end-to-end `await runtime.execute(...)` outcome assertion is strict-xfail pending
      kailash-py#1182 (audit-emit signing-bytes bug — journal 0001 / conformance.md); the
      compose + chain-carries-envelope assertions ship and pass now.
