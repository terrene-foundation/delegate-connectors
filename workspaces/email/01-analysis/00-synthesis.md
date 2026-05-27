# Analysis Synthesis — Email Connector (corrected against shipped kailash 2.26.2)

Reconciles `01-conformance-contract.md`, `02-connector-contract.md`,
`03-runtime-infra-topology.md` (three parallel deep-dive verification agents,
2026-05-27). Every claim here is grounded in introspection of the shipped wheel,
not the README or issue #1035 prose.

## Corrected architecture (ADRs)

### ADR-1: Subclass `Connector` ABC directly (NOT `LegacyInvokeConnector`)

`Connector.__abstractmethods__` = `{authenticate, invoke, read, write,
auth_verifier, ledger, revocation}` (4 methods + 3 properties), in
`kailash.delegate.dispatch`. `read(query)`/`write(action)` take a zero-arg async
thunk run **under audit**, returning `AttestedReadReceipt` / `SignedActionEnvelope`.

`LegacyInvokeConnector` REJECTED: its auto-proxied `read`/`write` emit empty,
explicitly-"unverifiable" receipts and its 3 trust properties RAISE on access
(`_LegacyAccessor`). That cannot meet email's audited IMAP-read / SMTP-write +
verifiable-receipt bar. Con (honest): direct shape is more up-front code — but the
legacy path's brevity IS the capability gap, not a shortcut.

### ADR-2: Runtime is `DelegateRuntime` + `DispatchSurface`, constructed directly

The README/brief/`#1035` `Delegate.compose(...connectors=..., pact_engine=...)` +
`await delegate.run()` **does not exist**. Shipped reality:

- `DelegateRuntime(*, dispatch_surface, audit_engine, cascade, envelope, identity, signer, posture=L5_DELEGATED)`
- `DispatchSurface(connector, signature, envelope, identity, *, audit_engine, trust_cascade, role, signer, verifier=None)`
- Entry: `runtime.execute(input_payload: dict) -> RuntimeExecutionResult` — **sync**, not `run()`, not async.
- `Delegate` is just an alias of `DelegateRuntime`.

### ADR-3: Audit is in-memory; trust is `Ed25519Verifier`. NO Postgres, NO PACT.

`AuditChainEngine(chain: TrustLineageChain)` is in-memory. `pact_engine` does not
exist; `kailash-pact` is not installed and not required. Trust verification =
`Ed25519Verifier(PrincipalDirectory(...))` (NOT `NullVerifier`, which rejects
everything by design). PACT/Postgres appear only as docstring aspirations
(`types.py:562`, `dispatch.py:348`).

### ADR-4: One test container — Mailpit (SMTP send + IMAP read). No Postgres/PACT containers.

Mailpit is the only single-container option exposing BOTH SMTP and IMAP (MailHog
lacks IMAP; GreenMail is a JVM fallback). Tier-2/3 real-infra = Mailpit only.

### ADR-5: Monorepo layout

`connectors/email/` → dist `delegate-connector-email`, namespace
`delegate_connectors.email` (PEP 420), `kailash>=2.24.0`, Apache-2.0 SPDX,
hatchling backend.

## Two blockers requiring user decision (see recommendation)

### BLOCKER-1: Canonical conformance vectors are NOT shipped + no runner ships

`ConformanceVectorLoader.load_canonical()` raises `FileNotFoundError` — the fixture
(`tests/fixtures/delegate-conformance/canonical.json`) lives only in the kailash-py
SOURCE tree, not the wheel. `validate_vector_set()` only checks set well-formedness;
there is NO connector-vs-vector execution harness in the package. So the brief's
"pass canonical conformance vectors" criterion is not runnable from the installed
package. Sourcing the fixture requires reading the kailash-py repo — a CROSS-REPO
read, BLOCKED by `repo-scope-discipline.md` without explicit user authorization.
(`expected` is a closed enum `{Accept, Reject, EscalateToHuman}`; `assert_receipts_agree`
deep-compares two `RuntimeExecutionResult.to_dict()` dicts.)

### BLOCKER-2: #1035 acceptance criteria are over-specified vs shipped API

"Pure-Python Delegate runs end-to-end vs a real PACT engine + real Postgres audit"
is unsatisfiable as written — the shipped runtime uses in-memory `AuditChainEngine`

- `Verifier`, with no PACT/Postgres hooks. The buildable path IS the shipped-API
  reality; #1035's letter is aspirational.

## What IS fully determined (no blocker)

The connector itself (`authenticate/read/write/invoke` + trust properties against
the real types), the runtime wiring, Mailpit real-infra integration tests, and the
package layout are all buildable now against the shipped API. Only the conformance
acceptance criterion is gated on BLOCKER-1.
