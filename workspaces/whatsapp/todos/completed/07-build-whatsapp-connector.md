# Todo 07 — Build `WhatsAppConnector(Connector)` core

**Implements:** `specs/connector-contract.md` § The interface + § Base-class decision (ADR-1) (+ `02-plans/02-connector-spec.md` § Responsibilities, Connector ABC-member mapping)
**Type:** Build (LOAD-BEARING CORE) · **Capacity:** single shard (~480 LOC load-bearing, 7 invariants)
**Depends:** 03, 04, 05, 06

**Value-anchor:** delivers the brief acceptance criteria "`WhatsAppConnector` satisfies `kailash.delegate.Connector` ABC — every abstract member implemented (ABC instantiation succeeds)" and "Receipts bind FULL identity (signer + action_id + observed_at); tamper of any field fails verification."

## Do

`src/delegate_connectors/whatsapp/connector.py` — `WhatsAppConnector(Connector)`
subclassing the ABC DIRECTLY (NOT `LegacyInvokeConnector` — ADR-1). Implement all 7 members:

- `authenticate(identity, envelope) -> Principal` — delegate to the resolver (todo 04);
  unknown → `ConnectorAuthenticationError`.
- `write(action, *, identity, envelope) -> SignedActionEnvelope` — `action` wraps
  `cloud_api.send` (todo 03); PII-redact the recipient (todo 02) before the signed
  canonical bytes; `build_action_signing_bytes` → Ed25519-sign → non-empty
  `SignedActionEnvelope`.
- `read(query, *, identity, envelope) -> (msgs, AttestedReadReceipt)` — `query` drains the
  ingest buffer (todo 05); PII-redact the sender in the manifest; `build_read_signing_bytes`
  → attest.
- `invoke(payload, *, identity, envelope) -> ConnectorInvocationResult` — order:
  `authenticate` (fail-closed) → template/window pre-flight `Reject` gate (todo 06) →
  audited `write` send → `ConnectorInvocationResult(payload, audit_events,
tenant_id_observed, external_side_effect=True)`.
- Properties `auth_verifier` → `Ed25519Verifier(directory)`; `ledger` →
  `InMemoryKnowledgeLedger` Protocol adapter (records event_type + PII-redacted payload
  only); `revocation` → `NeverRevokedChannel` Protocol adapter (v0: always live).
- Identity-binding helpers (mirror of email): `build_action_signing_bytes` /
  `build_read_signing_bytes` / `verify_action_envelope` / `verify_read_receipt`.
- `ConnectorAuthenticationError`.

## Invariants (7)

1. `isinstance(WhatsAppConnector(...), Connector)` — all abstractmethods satisfied.
2. `read`/`write` return real non-empty verifiable receipts (NOT the empty receipts that
   got `LegacyInvokeConnector` rejected).
3. Fail-closed auth: unknown identity → `ConnectorAuthenticationError` BEFORE any Cloud API call.
4. Pre-flight Reject gate (template/window) fires before the side effect.
5. Receipts bind FULL identity (signer + action_id/read_id + observed_at); tamper of any
   field fails verification.
6. PII-redacted payloads — no raw phone/`wa_id` in audit bytes, ledger records, or logs.
7. Trust properties return shipped/Protocol concretes, never raise.

## Acceptance

- [ ] ABC `isinstance` check passes.
- [ ] Unit (Tier-1): read/write return non-empty verifiable receipts (thunk stubbed at the
      SDK boundary only).
- [ ] Unit: tamper any signed field → `verify_*` returns false / raises (todo 12 adds the
      dedicated regression).
- [ ] Unit: unknown identity → `ConnectorAuthenticationError`, transport never called.
- [ ] No custom trust primitive authored (framework-first — reuse shipped `Ed25519Verifier`).
