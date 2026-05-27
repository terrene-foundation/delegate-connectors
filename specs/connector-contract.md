# Spec — Connector Contract

Authority: shipped `kailash.delegate.dispatch.Connector` (kailash 2.26.2),
verified by introspection 2026-05-27 (`workspaces/email/01-analysis/02-connector-contract.md`).

## The interface

`Connector` is an ABC. `__abstractmethods__` = 4 methods + 3 properties. A
connector MUST implement all 7. Import the non-`__all__` types from
`kailash.delegate.dispatch`.

### Methods

| Member         | Signature                                                            | Returns                         |
| -------------- | -------------------------------------------------------------------- | ------------------------------- |
| `authenticate` | `(identity: DelegateIdentity, envelope: DelegateConstraintEnvelope)` | `Principal`                     |
| `invoke`       | `(input_payload: dict, *, identity, envelope)`                       | `ConnectorInvocationResult`     |
| `read`         | `(query: Callable[[], Awaitable[T]], *, identity, envelope)`         | `tuple[T, AttestedReadReceipt]` |
| `write`        | `(action: Callable[[], Awaitable[Any]], *, identity, envelope)`      | `SignedActionEnvelope`          |

`read`/`write` take a **zero-arg async thunk** the connector executes UNDER AUDIT —
the connector wraps the external call (IMAP fetch / SMTP send) in the thunk and the
audited path produces the attested/signed receipt.

### Properties (trust hooks — structural Protocols)

| Property        | Type                | Purpose                         |
| --------------- | ------------------- | ------------------------------- |
| `auth_verifier` | `AuthVerifier`      | verify a signed identity        |
| `ledger`        | `KnowledgeLedger`   | record/lookup knowledge entries |
| `revocation`    | `RevocationChannel` | revocation checks               |

These are `Protocol`s — satisfied by structural binding (no subclassing). Reuse
shipped concretes; do NOT author custom trust primitives (framework-first).

## Type catalog (all in `kailash.delegate.dispatch` unless noted)

- `DelegateIdentity` — the dispatch identity presented to the connector.
- `Principal(delegate_id, tenant_id, claims)` — `authenticate` return.
- `ConnectorInvocationResult(payload, audit_events, tenant_id_observed, external_side_effect)`.
- `ConstraintEnvelope` / `DelegateConstraintEnvelope` (top-level export) — monotonic-tightening constraints; widening MUST raise (`EnvelopeWideningError`).
- `AttestedReadReceipt`, `SignedActionEnvelope` — audit receipts.
- Verifiers (top-level export): `Ed25519Verifier(directory)`, `NullVerifier()` (rejects all — test-negative only), `Verifier` (protocol).

## Base-class decision (ADR-1)

Subclass `Connector` DIRECTLY. `LegacyInvokeConnector` is REJECTED: it implements
only `invoke`; its proxied `read`/`write` emit empty "unverifiable" receipts and its
trust properties raise on access — structurally cannot produce verifiable audit
receipts.

## Divergence from README/issue (verified TRUE)

README lines ~20-23 describe `connect() / identify() / authenticate() / normalize()`.
`connect`, `identify`, `normalize` DO NOT EXIST in the shipped ABC. `authenticate`
exists but returns a `Principal` (README's "Posture + Genesis write" description is
wrong). README needs a correction PR (tracked as a follow-up; not connector code).
