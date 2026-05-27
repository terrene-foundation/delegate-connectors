# Spec — Runtime Composition

Authority: shipped `kailash.delegate` runtime (kailash 2.26.2), verified
`workspaces/email/01-analysis/03-runtime-infra-topology.md`. The
`Delegate.compose(...)` + `await delegate.run()` + `pact_engine=` shape from the
README/issue **does not exist** — `Delegate` is an alias of `DelegateRuntime`.

## Composition (direct construction)

```python
from kailash.delegate import (
    DelegateRuntime, DispatchSurface, ConstraintEnvelope, PrincipalDirectory,
    AuditChainEngine, Ed25519Verifier,
)
# 1. directory + verifier
directory = PrincipalDirectory(...)              # known principals
verifier  = Ed25519Verifier(directory)
# 2. audit (in-memory — NO Postgres)
audit = AuditChainEngine(chain=...)              # TrustLineageChain
# 3. dispatch surface wraps the connector
surface = DispatchSurface(
    connector, signature, envelope, identity,
    audit_engine=audit, trust_cascade=cascade, role=role, signer=signer,
    verifier=verifier,
)
# 4. runtime
runtime = DelegateRuntime(
    dispatch_surface=surface, audit_engine=audit, cascade=cascade,
    envelope=envelope, identity=identity, signer=signer,
    posture="L5_DELEGATED",
)
# 5. execute — SYNC, returns RuntimeExecutionResult
result = runtime.execute(input_payload={...})
```

## Contracts

- `runtime.execute(input_payload: dict) -> RuntimeExecutionResult` — synchronous.
- `RuntimeExecutionResult.to_dict()` is the input to `assert_receipts_agree(a, b)`
  (cross-impl audit-chain agreement; timestamps excluded from the deep compare).
- Envelope monotonic-tightening: widening MUST raise `EnvelopeWideningError`.
- `posture` defaults to `L5_DELEGATED`.

## What the email connector must supply to the runtime

The `DispatchSurface` needs: the `EmailConnector` instance, a `signature`
(application-supplied — for v0 a minimal fixture signature), an `envelope`
(`ConstraintEnvelope`), an `identity` (`DelegateIdentity`), the `audit_engine`,
`trust_cascade`, `role`, `signer`, and `verifier`. v0 uses the spine-shipped
concretes for everything except the connector.
