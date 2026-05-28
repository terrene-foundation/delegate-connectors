# Todo 04 — Build `TelegramConnector(Connector)` core

**Implements:** `specs/connector-contract.md` (full ABC + ADR-1)
(+ `02-plans/02-connector-spec.md` § Responsibilities)
**Type:** Build (LOAD-BEARING CORE) · **Capacity:** single shard (~350 LOC, 5 invariants — at budget)
**Depends:** 02, 03

## Do

`src/delegate_connectors/telegram/connector.py` — `TelegramConnector(Connector)`
subclassing the ABC DIRECTLY (NOT `LegacyInvokeConnector` — ADR-1, whose proxied
read/write emit empty unverifiable receipts). Implement all 4 methods + 3 properties:

- `authenticate(identity, envelope) -> Principal` — delegate to the dual-keyed resolver
  (todo 03); unknown → `ConnectorAuthenticationError` (closed-enum `Reject`, fail-closed).
- `write(action, *, identity, envelope) -> SignedActionEnvelope` — `action` is the
  zero-arg async thunk wrapping `transport.send` (todo 02); execute under audit. Sign
  over FULL identity (signer_delegate_id + action_id + observed_at), NOT payload-only.
- `read(query, *, identity, envelope) -> (updates, AttestedReadReceipt)` — `query`
  wraps `transport.get_updates` (todo 02); execute under audit; receipt binds the
  message-id manifest + attester identity (no message bodies in the signed payload).
- `invoke(payload, *, identity, envelope) -> ConnectorInvocationResult` — single-method
  entry: `authenticate` FIRST (fail-closed gate, BEFORE any Bot API call fires), then
  dispatch to the audited `write` path; return `(payload, audit_events,
tenant_id_observed, external_side_effect=True)`.
- Properties: `auth_verifier` → `Ed25519Verifier(directory)`; `ledger` /
  `revocation` → Protocol-satisfying deterministic adapters (framework-first; no custom
  trust primitive authored).
- Reuse the channel-agnostic signing helpers (`build_action_signing_bytes` /
  `build_read_signing_bytes` / `verify_action_envelope` / `verify_read_receipt`) — same
  identity-binding shape as email's connector contract.

## Invariants (5)

1. `isinstance(TelegramConnector(...), Connector)` — every abstractmethod satisfied
   (ABC instantiation succeeds).
2. `invoke` authenticates FIRST: an unknown sender raises `ConnectorAuthenticationError`
   and ZERO Bot API send fires on the hot path.
3. `read` emits a real `AttestedReadReceipt`; `write` a real `SignedActionEnvelope`
   (NOT empty) — receipts bind FULL identity (signer + action_id/read_id + observed_at),
   so tamper of any bound field fails verification.
4. No credentials (`TELEGRAM_BOT_TOKEN`/URL) in any log line or audit payload.
5. Trust properties return Protocol-satisfying concretes/adapters, never raise; no
   custom trust primitive authored.

## Acceptance

- [ ] ABC `isinstance` check passes.
- [ ] Unit: read/write return non-empty verifiable receipts (Tier-1, thunk stubbed at
      the SDK boundary only — the thunk, not the connector contract).
- [ ] Unit: tampering a bound identity field (signer/attester) fails verification.
- [ ] No custom trust primitive authored; `grep` clean for token literals.
