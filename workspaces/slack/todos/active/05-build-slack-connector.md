# Todo 05 — Build `SlackConnector(Connector)` core (`connector.py`)

**Implements:** `specs/connector-contract.md` (full ABC) (+ `02-plans/02-connector-spec.md` § Responsibilities, § Unknown-sender disposition, § Security)
**Type:** Build (LOAD-BEARING CORE) · **Capacity:** single shard (~400 LOC, 7 invariants — upper budget; Tier-1 unit loop is live during this shard)
**Depends:** 02, 03, 04

## Do

`src/delegate_connectors/slack/connector.py` — `SlackConnector(Connector)`
subclassing the ABC DIRECTLY (NOT `LegacyInvokeConnector` — ADR-1). Implement all
7 abstract members:

- `authenticate(identity, envelope) -> Principal` — resolve `identity.delegate_id`
  against `SlackPrincipalResolver` (todo 04). Unknown → `ConnectorAuthenticationError`
  (fail-closed `Reject`).
- `write(action, *, identity, envelope) -> SignedActionEnvelope` — `action` is the
  zero-arg async thunk wrapping `chat.postMessage` (todo 02). Execute under audit;
  canonicalize the post result; Ed25519-sign over FULL identity (payload +
  signer_delegate_id + action_id + observed_at); return a NON-empty
  `SignedActionEnvelope`.
- `read(query, *, identity, envelope) -> (messages, AttestedReadReceipt)` — `query`
  is the zero-arg async thunk wrapping `conversations.history` (todo 02). Execute
  under audit; build a canonical manifest (channel + message count + message `ts`
  ids — NO message body bytes in the audited payload, mirroring email's
  `_read_manifest`); sign over FULL identity; return the messages + a verifiable
  `AttestedReadReceipt`.
- `invoke(input_payload, *, identity, envelope) -> ConnectorInvocationResult` — the
  hot-path entry: `authenticate` FIRST (fail-closed gate BEFORE any
  `chat.postMessage` fires), then build `OutboundSlackMessage` (id-validate +
  text-escape, todo 03), send via the audited `write` path, return
  `ConnectorInvocationResult(payload, audit_events, tenant_id_observed,
external_side_effect=True)`.
- Properties: `auth_verifier` → the supplied `Ed25519Verifier`; `ledger` →
  `InMemoryKnowledgeLedger` (Protocol-satisfying deterministic adapter — the SDK
  ships only the Protocol); `revocation` → `NeverRevokedChannel` (Protocol-satisfying).
- Connector-local receipt helpers: `build_action_signing_bytes` /
  `build_read_signing_bytes` / `verify_action_envelope` / `verify_read_receipt`
  (re-implemented per-connector; the canonical-json signing contract is shared via
  `kailash.trust._json.canonical_json_dumps`).
- Class metadata: `connector_id = "delegate-connector-slack"`,
  `connector_kind = "slack"`, `requires_capabilities = frozenset({"slack.post"})`.

## Invariants (7)

1. `isinstance(SlackConnector(...), Connector)` — all abstractmethods satisfied
   (ABC instantiation succeeds).
2. `authenticate` runs FIRST on the `invoke` hot path — unknown sender raises
   `ConnectorAuthenticationError` BEFORE any Slack API call fires.
3. Receipts bind FULL identity (signer/attester + action_id/read_id + observed_at),
   NOT bare payload — two identical posts produce different signed bytes.
4. `read` emits a real `AttestedReadReceipt`; `write` a real `SignedActionEnvelope`
   (NOT empty — the reason `LegacyInvokeConnector` was rejected).
5. The read manifest carries message `ts` ids + count only — NEVER message body
   bytes; no credential ever enters the audit payload or any log line.
6. `tenant_id_observed` echoes the resolved principal's tenant.
7. Trust properties return shipped/Protocol-satisfying concretes, never raise.

## Acceptance

- [ ] Unit: `isinstance` ABC check passes (Tier-1).
- [ ] Unit: read/write return NON-empty receipts that verify under a real
      `Ed25519Verifier` (thunk stubbed at the SDK boundary only).
- [ ] Unit: unknown sender → `ConnectorAuthenticationError` raised BEFORE the
      `chat.postMessage` thunk is invoked (assert the thunk never ran).
- [ ] Unit: no custom trust primitive authored (trust properties are the shipped /
      Protocol-satisfying concretes).
