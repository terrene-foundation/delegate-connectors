# Brief — Email Connector (v0)

> **Provenance:** Agent-drafted 2026-05-27 under `/autonomize` (user delegated brief
> authoring after directing autonomous execution). Grounded in the **shipped**
> `kailash.delegate` API (kailash 2.26.2), the README connector position, and
> issue #1035 acceptance criteria. **User amendment expected** — flag anything
> mis-scoped.

## Goal

Ship the first OSS Python connector in this monorepo: an **email connector** that
implements the `kailash.delegate.Connector` contract and passes the canonical
conformance vector set. It is the reference that proves the OSS spine is usable by
a real connector, mirroring the "stub email connector passes conformance" line in
#1035's acceptance criteria — but a real implementation, not a stub.

## CRITICAL: README contract is stale vs shipped API

The repo README (line 20) states the connector responsibility as
`connect() / identify() / authenticate() / normalize()`. **None of those four
methods exist in the shipped `Connector` ABC.** Verified against kailash 2.26.2:

| README (stale)   | Shipped `kailash.delegate.Connector` (2.26.2)                                                               |
| ---------------- | ----------------------------------------------------------------------------------------------------------- |
| `connect()`      | (no equivalent — wiring is constructor/property based)                                                      |
| `identify()`     | folded into `authenticate()`                                                                                |
| `authenticate()` | `authenticate(identity: DelegateIdentity, envelope: DelegateConstraintEnvelope) -> Principal`               |
| `normalize()`    | (no equivalent — payload shaping happens inside `invoke`/`read`/`write`)                                    |
| —                | `invoke(payload, *, identity, envelope) -> ConnectorInvocationResult`                                       |
| —                | `read(query, *, identity, envelope) -> (payload, AttestedReadReceipt)`                                      |
| —                | `write(action, *, identity, envelope) -> SignedActionEnvelope`                                              |
| —                | properties: `auth_verifier -> AuthVerifier`, `ledger -> KnowledgeLedger`, `revocation -> RevocationChannel` |

The connector design MUST follow the shipped ABC. The README's connector section
needs a correction PR (separate from connector code). `/analyze` will verify this
divergence independently (parallel brief-claim verification).

## Shipped contract reference (kailash 2.26.2)

- **Base options**: implement `Connector` (ABC, 4 methods + 3 properties) directly,
  OR extend `kailash.delegate.dispatch.LegacyInvokeConnector` (concrete adapter —
  supply an `async invoke(...)` callable; read/write derive from it). v0 SHOULD start
  from `LegacyInvokeConnector` unless `/analyze` finds the audited read/write split
  is required for email semantics.
- **Key types**: `DelegateIdentity` (dispatch identity), `Principal(delegate_id,
tenant_id, claims)` (authenticate return), `ConnectorInvocationResult(payload,
audit_events, tenant_id_observed, external_side_effect)`, `DelegateConstraintEnvelope`,
  `AttestedReadReceipt`, `SignedActionEnvelope`.
- **Conformance**: `kailash.delegate.conformance.ConformanceVectorLoader.load_canonical()`
  → `validate_vector_set(vectors)` → connector must satisfy each vector's
  `(given, behaviour, expected)`. `assert_receipts_agree(...)` for cross-impl
  receipt agreement.

## v0 Scope (tight — expand only if /analyze justifies)

**In scope:**

1. An `EmailConnector` implementing the shipped `Connector` contract (base TBD by
   `/analyze`: ABC-direct vs `LegacyInvokeConnector`).
2. **Outbound** email send as the primary `write`/`invoke` action (SMTP).
3. **Inbound** email read as the `read` path (IMAP), returning an attested receipt.
4. `authenticate()` resolving a sender/recipient `DelegateIdentity` to a `Principal`
   against a `PrincipalDirectory`.
5. Wiring `auth_verifier` / `ledger` / `revocation` to the spine-provided defaults
   (e.g. `Ed25519Verifier` / `NullVerifier`) — no custom trust primitives.
6. Passing `ConformanceVectorLoader.load_canonical()` vectors.
7. Tier 1/2/3 tests with **real infrastructure** (no mocks at the boundary per
   #1035 + testing rules): real SMTP/IMAP (Dockerized, e.g. GreenMail/Mailpit),
   real PACT engine, real Postgres audit.

**Out of scope (v0 — do not chase):**

- OAuth2 / Gmail / M365 provider auth (start with SMTP/IMAP credentials from env).
- HTML/MIME rendering, attachment normalization beyond passthrough.
- Calendar invites, S/MIME, threading/References-header chain integrity.
- Dispatch, trust-gate, classification, supervisor wiring (spine concerns, per README).
- The other three connectors (whatsapp/slack/telegram).

## Acceptance criteria

- [ ] `EmailConnector` satisfies `kailash.delegate.Connector` (or documented
      `LegacyInvokeConnector` extension) — `isinstance`/ABC check passes.
- [ ] Canonical conformance vectors pass:
      `validate_vector_set(ConformanceVectorLoader.load_canonical())` green against
      the connector.
- [ ] Outbound send + inbound read run end-to-end against real Dockerized SMTP/IMAP
      with a real PACT engine + real Postgres audit (NO mocks at the boundary).
- [ ] `authenticate()` resolves a known sender to a `Principal`; unknown sender
      handled per spec (reject vs unauthenticated — `/analyze` to specify).
- [ ] Audit receipts (`AttestedReadReceipt` / `SignedActionEnvelope`) emitted on
      read/write and verify under the spine verifier.
- [ ] Apache 2.0 headers; no dependency on the proprietary Rust sibling.
- [ ] README connector-contract section corrected (separate doc PR).

## Open questions for /analyze

1. `LegacyInvokeConnector` vs direct `Connector` ABC — which fits email's
   read(IMAP)/write(SMTP) split, given `invoke` is the legacy single-method shape?
2. `Principal` resolution policy: exact-match directory, alias, or domain rule?
   What is the unknown-sender disposition?
3. What do the **canonical conformance vectors actually assert** about a connector?
   (Load them, read `given/behaviour/expected`, derive the real contract surface.)
4. Real-infra test topology: which SMTP/IMAP container; how the PACT engine +
   Postgres audit are stood up in CI.
5. Monorepo layout: `connectors/email/` package shape, pyproject, namespace.
