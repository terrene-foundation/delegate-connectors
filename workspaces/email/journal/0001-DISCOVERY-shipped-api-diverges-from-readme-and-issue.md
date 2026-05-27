# DISCOVERY — Shipped kailash.delegate API diverges from README + issue #1035

**Date:** 2026-05-27
**Phase:** /analyze
**Evidence:** introspection of kailash 2.26.2 (repo `.venv`), three parallel
verification agents → `01-analysis/0{1,2,3}-*.md` + `00-synthesis.md`.

## Finding

The connector + runtime contract described in the repo README and issue #1035 does
NOT match the shipped `kailash.delegate` API. Three independent divergences,
each verified by introspection:

1. **Connector contract** — README says `connect/identify/authenticate/normalize`.
   Shipped `Connector` ABC = `authenticate / invoke / read / write` (methods) +
   `auth_verifier / ledger / revocation` (properties). `connect`, `identify`,
   `normalize` do not exist.
2. **Runtime** — README/#1035 show `Delegate.compose(connectors=..., pact_engine=...)`
   - `await delegate.run()`. Shipped: construct `DelegateRuntime(...)` +
     `DispatchSurface(...)` directly; `runtime.execute(payload)` is **sync**.
     `Delegate` is an alias of `DelegateRuntime`. No `compose`, no `pact_engine`, no `run`.
3. **Audit/trust** — `pact_engine` doesn't exist; `kailash-pact` not installed/needed.
   Audit is in-memory `AuditChainEngine`; trust is `Ed25519Verifier`.

## Why it matters

Building straight from the README would have produced a connector that fails the
real ABC. Verifying the spine BEFORE writing code (task #2) caught this. The base
class also flipped on evidence: `LegacyInvokeConnector` looks simpler but emits
empty unverifiable receipts + its trust properties raise → must subclass `Connector`
directly (ADR-1).

## Follow-up

README connector-contract section (lines ~20-23) is stale → needs a correction PR,
separate from connector code.
