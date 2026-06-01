# P0-10a — Build the connector_builder() compose-ceremony factory (absorbs the ~10-concrete ceremony; wires host signer; pins AuthVerifier to SDK Ed25519Verifier)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~200 LOC
> **Depends on:** P0-04, P0-07, P0-08b
> **Implements:** architecture §3.3; architecture §7 Phase 0; specs sdk_provided_vs_local (connector_builder net-new; AuthVerifier SDK-provided); specs trust_primitive_interfaces (AuthVerifier)

## What (≤3 sentences)

Build delegate.connector_builder(connector, *, signer_callback=...) compose-ceremony half — does not exist today (zero hits). It absorbs the ~250-LOC compose ceremony spanning ~10 spine concretes (PrincipalDirectory + Ed25519Verifier + GenesisRecord + TrustLineageChain + AuditChainEngine + TenantScopedCascade with real grant proof + Role + resolver + DispatchSurface + DelegateRuntime), wires the host signer from P0-08b (not a connector-held key), and pins AuthVerifier to the SDK Ed25519Verifier as the single canonical host binding. Split out of the original P0-10 per capacity HIGH finding (the ~10-concrete ceremony wiring + the protocol gate's net-new control-flow overflowed the 5-10 ceiling together). The AuthVerifier pin folds in the former P0-03 (completeness LOW: P0-03's standalone re-export risked being an imported-by-nobody orphan; the factory is the single consumer).

## Deliverable

A new `delegate_connectors_host/connector_builder.py` exporting the factory that performs the compose ceremony once, wires the host-side signer (P0-08b), and references AuthVerifier as the SDK Ed25519Verifier via a single canonical binding (the former P0-03 re-export, now consumed here).

## Files touched

- delegate_connectors_host/connector_builder.py (new — the compose-ceremony factory + canonical AuthVerifier binding)
- delegate_connectors_host/trust_primitives.py (new — AuthVerifier = Ed25519Verifier canonical alias, IMPORTED by connector_builder; folded from former P0-03)
- connectors/email/src/delegate_connectors/email/compose.py (ceremony the factory absorbs — reference for the shared build)

## Invariants (MUST hold)

- factory performs the compose ceremony once (directory/verifier/genesis/chain/audit/cascade-with-real-grant-proof/role/resolver/DispatchSurface/DelegateRuntime)
- factory wires the host-side signer from P0-08b, NOT a connector-held raw key
- AuthVerifier is pinned to the SDK Ed25519Verifier via ONE canonical host binding that the factory IMPORTS (no local AuthVerifier placeholder; the binding is consumed, not orphaned — completeness LOW finding folds former P0-03 here)
- the returned composition is a runnable DelegateRuntime equivalent to the hand-rolled compose
- verify(canonical_bytes, signature, signer_delegate_id)->bool signature preserved unchanged

## Value anchor

Architecture §3.3 + §7 Phase 0: "ship the versioned connector_builder() factory". Absorbs the ~250-LOC compose ceremony every connector hand-copies. specs sdk_provided_vs_local confirms connector_builder is net-new (zero hits today) and AuthVerifier is the one already-production primitive Phase 0 keeps.

## Acceptance criteria

- [ ] connector_builder() absorbs the compose ceremony and returns a runnable composed runtime
- [ ] the factory wires the host signer (P0-08b) and pins AuthVerifier to the SDK Ed25519Verifier via a single canonical, imported (non-orphan) binding
- [ ] no local AuthVerifier placeholder is created

## Test plan

Unit: factory composes a runnable DelegateRuntime equivalent to the hand-rolled compose; assert the composed runtime signs via the host signer (P0-08b), not a connector-held key; assert the factory references AuthVerifier via the single canonical SDK Ed25519Verifier binding (the alias is imported and used — not an orphan). Behavioral: a connector composed via the factory produces verifiable receipts end-to-end.
