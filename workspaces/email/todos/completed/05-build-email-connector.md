# Todo 05 — Build `EmailConnector(Connector)` core

**Implements:** `specs/connector-contract.md` + `specs/email-connector.md`
**Type:** Build (LOAD-BEARING CORE) · **Capacity:** single shard (~280 LOC, 6 invariants)
**Depends:** 02, 03, 04

## Do

`src/delegate_connectors/email/connector.py` — `EmailConnector(Connector)`
subclassing the ABC DIRECTLY (NOT `LegacyInvokeConnector` — ADR-1). Implement all 7:

- `authenticate(identity, envelope) -> Principal` — delegate to directory (todo 04).
- `write(action, *, identity, envelope) -> SignedActionEnvelope` — `action` is the
  zero-arg async thunk wrapping `smtp.send` (todo 02); execute under audit.
- `read(query, *, identity, envelope) -> (msgs, AttestedReadReceipt)` — `query` wraps
  `imap.fetch` (todo 03); execute under audit.
- `invoke(payload, *, identity, envelope) -> ConnectorInvocationResult` — single-method
  entry; dispatch to send; return `(payload, audit_events, tenant_id_observed,
external_side_effect=True)`.
- Properties `auth_verifier` → `Ed25519Verifier(directory)`; `ledger` / `revocation`
  → shipped concretes (framework-first; no custom primitives).

## Invariants (6)

1. `isinstance(EmailConnector(...), Connector)` — all abstractmethods satisfied.
2. `read` emits a real `AttestedReadReceipt`; `write` a real `SignedActionEnvelope`
   (NOT empty — the reason LegacyInvokeConnector was rejected).
3. Unknown sender → `Reject` (inherited from todo 04).
4. No secrets in audit payloads or logs.
5. Envelope monotonic-tightening respected (widening raises).
6. Trust properties return shipped concretes, never raise.

## Acceptance

- [ ] ABC `isinstance` check passes.
- [ ] Unit: read/write return non-empty verifiable receipts (Tier-1, thunk stubbed at
      SDK boundary only).
- [ ] No custom trust primitive authored.
