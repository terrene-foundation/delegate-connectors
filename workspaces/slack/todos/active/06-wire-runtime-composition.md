# Todo 06 — Wire connector into DelegateRuntime (`compose.py`)

**Implements:** `specs/runtime-composition.md` (+ `02-plans/02-connector-spec.md` § Responsibilities)
**Type:** WIRE (real composition, real data end-to-end) · **Capacity:** single shard (~200 LOC, 4 invariants)
**Depends:** 05

## Do

- `src/delegate_connectors/slack/compose.py` — a helper that composes a runnable
  `DelegateRuntime` around a `SlackConnector` (mechanical mirror of email's
  `compose.py`):
  - build `PrincipalDirectory` + `Ed25519Verifier` (real verifier, NOT
    `NullVerifier`);
  - in-memory `AuditChainEngine(chain=TrustLineageChain)`;
  - `TenantScopedCascade` with a root grant;
  - `DispatchSurface(connector, signature, envelope, identity, audit_engine=…,
trust_cascade=…, role=…, signer=…, verifier=…)`;
  - then `DelegateRuntime(dispatch_surface=…, audit_engine=…, cascade=…,
envelope=…, identity=…, signer=…, posture="L5_DELEGATED")`.
  - `build_slack_runtime(...)`, `SlackV0Signature` (minimal v0 fixture signature —
    application-supplied, documented as a v0 placeholder, NOT a stub-for-production),
    `ComposedSlackRuntime`.
- Entry is `await runtime.execute(input_payload)` — the coroutine form
  (`runtime.execute` is ASYNC in kailash 2.26.2 per `specs/runtime-composition.md`).

## Invariants (4)

1. Uses real shipped concretes for audit/verifier/cascade — no mocks; the verifier
   is `Ed25519Verifier`, never `NullVerifier`.
2. The composing identity is registered in the `PrincipalDirectory` (so the
   verifier resolves it).
3. The cascade carries a root grant proof (composition does not raise on a
   monotonic-tightening envelope).
4. `await runtime.execute(...)` is wired as a coroutine; the composed runtime is
   reusable (no per-call global state).

## Acceptance

- [ ] Unit (Tier-1, thunk stubbed at SDK boundary): `build_slack_runtime(...)`
      composes without raising; `await runtime.execute({...post...})` returns a
      `RuntimeExecutionResult`.
- [ ] Unit: `result.to_dict()` is stable across two identical runs (feeds
      `assert_receipts_agree` in todo 08).
- [ ] The connector's own signed `write` envelope verifies under the composed
      `Ed25519Verifier` (the end-to-end `execute()` outcome assertion itself is
      strict-xfail per todo 09, gated on kailash-py#1182).
