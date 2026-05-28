# Analysis 03 — Connector Contract + Runtime Mapping

Grounded in introspection of the shipped `kailash.delegate` (kailash 2.26.2,
2026-05-27, repo-local venv) and the shipped email connector as the reference
implementation. Inherits ADR-1..5 from the email synthesis; this doc maps them
onto the WhatsApp channel and records two SHIPPED-API facts that correct stale
prose.

## The ABC (introspected, verbatim)

`kailash.delegate.dispatch.Connector.__abstractmethods__` =
`{authenticate, invoke, read, write, auth_verifier, ledger, revocation}`
(4 methods + 3 properties). Signatures:

```
authenticate(self, identity: DelegateIdentity, envelope: DelegateConstraintEnvelope) -> Principal
invoke(self, input_payload: dict, *, identity, envelope) -> ConnectorInvocationResult
read(self, query: Callable[[], Awaitable[T]], *, identity, envelope) -> tuple[T, AttestedReadReceipt]
write(self, action: Callable[[], Awaitable[Any]], *, identity, envelope) -> SignedActionEnvelope
```

All four methods are `async def` in the email reference. The trust properties
are `Protocol`s satisfied structurally (no subclassing) — reuse shipped concretes
and Protocol-satisfying deterministic adapters, never custom trust primitives.

Receipt types (introspected):

- `AttestedReadReceipt(read_id: UUID, canonical_bytes: bytes, attestation: bytes, attester_delegate_id: str, observed_at: datetime)`
- `SignedActionEnvelope(action_id: UUID, canonical_bytes: bytes, signature: bytes, signer_delegate_id: str, payload: dict)`
- `Principal(delegate_id: str, tenant_id: str | None, claims: dict)`
- `ConnectorInvocationResult(payload: dict, audit_events: tuple[DelegateEventType, ...], tenant_id_observed: str | None, external_side_effect: bool)`

## ABC-member → WhatsApp behaviour

| ABC member      | WhatsApp behaviour                                                                                                                                                                                                          |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate`  | Resolve the dispatch identity's `delegate_id` to a `Principal` via `WhatsAppPrincipalResolver` (E.164-keyed + delegate_id-keyed). Unknown → `ConnectorAuthenticationError` (fail-closed `Reject`).                          |
| `write`         | `action` is a zero-arg async thunk wrapping the **Cloud API `POST /messages`**. Run under audit; canonicalize with PII-REDACTED recipient; Ed25519-sign; return a non-empty `SignedActionEnvelope`.                         |
| `read`          | `query` is a zero-arg async thunk that **drains the inbound webhook buffer** (pops the next verified inbound message[s]). Run under audit; canonicalize with PII-redacted sender; return `(messages, AttestedReadReceipt)`. |
| `invoke`        | Dispatch hot-path: `authenticate` FIRST (fail-closed), THEN template/window pre-flight gate, THEN send via the audited `write` path. Returns `ConnectorInvocationResult(external_side_effect=True)`.                        |
| `auth_verifier` | Returns the supplied `Ed25519Verifier(PrincipalDirectory)` (shipped concrete).                                                                                                                                              |
| `ledger`        | Protocol-satisfying in-memory `KnowledgeLedger` adapter (mirror of email's `InMemoryKnowledgeLedger`). Records event_type + PII-redacted payload only.                                                                      |
| `revocation`    | Protocol-satisfying `NeverRevokedChannel` adapter (mirror of email's). v0 has no revocation source wired.                                                                                                                   |

The `invoke` hot path inserts ONE extra gate vs email: after the fail-closed
`authenticate`, before the send, the template-approval + 24h-window pre-flight
check (Analysis 02) fires. A free-form send outside the window → `Reject`; an
un-approved template → `Reject`. Both raise BEFORE the HTTPS POST. This is the
WhatsApp delta on the otherwise-identical email `invoke` shape.

## Receipt identity binding (cross-channel invariant)

Mirror the email helpers exactly:
`build_action_signing_bytes(payload, *, signer_delegate_id, action_id, observed_at)`
and `build_read_signing_bytes(manifest, *, attester_delegate_id, read_id, observed_at)`
sign over the FULL receipt identity (not the bare payload), so two sends with an
identical message body produce DIFFERENT signed bytes (distinct `action_id` +
`observed_at`) and signer / action-id / observed-at are cryptographically bound.
`verify_action_envelope` / `verify_read_receipt` re-derive the canonical bytes
from the envelope's OWN identity fields and check (a) byte-equality AND (b)
Ed25519 verification — tamper of any field fails verification. The
WhatsApp-specific point: the `payload`/`manifest` that enters the signed bytes
carries the **PII-redacted** recipient/sender token (`wa:<hmac8>`), never the
raw E.164.

## Runtime composition (ADR-2) — TWO stale-prose corrections

Inherits ADR-2: runtime is `DelegateRuntime` + `DispatchSurface` constructed
directly. `Delegate.compose(...)` / `delegate.run()` DO NOT EXIST.

### Correction 1 (carry-forward, confirmed): no `Delegate.compose` / `delegate.run`

Introspection confirms `DelegateRuntime` + `DispatchSurface` direct construction
is the only path; `Delegate` is an alias of `DelegateRuntime`. README/#1035 prose
remains stale. No change vs email.

### Correction 2 (NEW — resolves a brief vs spec discrepancy): `runtime.execute()` IS async

The brief's ADR-2 instruction says to "confirm the CURRENT `execute()` signature

- whether it is sync or async ... AND introspecting the wheel; note any
  discrepancy you find." Here is the discrepancy:

* `workspaces/email/01-analysis/00-synthesis.md` ADR-2 states:
  "`runtime.execute(...)` — **sync**, not `run()`, not async."
* The corrected spec `specs/runtime-composition.md` (PR #5) states:
  "`async runtime.execute(input_payload: dict) -> RuntimeExecutionResult` —
  coroutine ... callers MUST `await` it."
* **Introspection of the shipped wheel (kailash 2.26.2)**:
  `inspect.iscoroutinefunction(DelegateRuntime.execute)` returns **`True`**.
  Signature: `execute(self, input_payload: dict[str, Any]) -> RuntimeExecutionResult`.

**Verdict: `runtime.execute()` is ASYNC (a coroutine).** The corrected spec
(`runtime-composition.md`, PR #5) is RIGHT; the email synthesis's "sync" line is
STALE and must not be propagated. The WhatsApp connector — and its e2e harness —
MUST `await runtime.execute(...)`. This is recorded as a brief correction in the
architecture plan and a journal DISCOVERY entry.

## Composition wiring (verbatim shipped signatures)

```
DispatchSurface(connector, signature, envelope, identity, *,
    audit_engine, trust_cascade, role, signer, verifier=None)
DelegateRuntime(*, dispatch_surface, audit_engine, cascade,
    envelope, identity, signer, posture=Posture.L5_DELEGATED)
result = await runtime.execute(input_payload={...})   # coroutine
```

The `WhatsAppConnector` instance is the only application-supplied object that
differs from email; everything else (signature fixture, envelope, identity,
audit engine, cascade, role, signer, verifier) uses spine-shipped concretes,
identical to email's wiring.

## Audit + trust (ADR-3, carry-forward)

In-memory `AuditChainEngine(chain: TrustLineageChain)`; trust =
`Ed25519Verifier(PrincipalDirectory)`. NO Postgres, NO PACT. #1035's "real PACT

- real Postgres" is aspirational; the buildable path is the shipped in-memory
  API. No WhatsApp-specific change.

## Conformance (ADR-4, carry-forward)

The canonical vector set is vendored at
`tests/fixtures/delegate-conformance/canonical.json` (5 vectors: DV-3/5/7/9/10,
4 Reject + 1 Accept). REUSE it via a vendored loader mirroring email's
`VendoredConformanceLoader`; do NOT re-source from kailash-py. Per-vector outcome
assertion + end-to-end via `runtime.execute()` are strict-xfail pending
kailash-py#1182 (the audit-emit signs payload bytes while `AuditChainEngine`
verifies full-entry signing bytes, so `runtime.execute()` returns `phase=="failed"`
on any real verifier). Mirror email's exact treatment: the ABC-composition
harness + well-formedness gate ship ACTIVE now; per-vector + e2e are strict-xfail.

## Package layout (ADR-5, carry-forward)

`connectors/whatsapp/` → dist `delegate-connector-whatsapp`, namespace
`delegate_connectors.whatsapp` (PEP 420), `kailash>=2.24.0`, Apache-2.0 SPDX,
hatchling backend. New dependency vs email: `httpx>=0.27` (async HTTPS client for
the Cloud API). `cryptography>=42.0` carries forward (Ed25519 + the PII HMAC).
