# Spec — WhatsApp Connector (v0)

> **Status: design spec (v0) — not yet implemented.** Per `rules/spec-accuracy.md`
> Rule 5, a spec for unshipped behavior lives in `02-plans/`, not `specs/`. This
> promotes to `specs/whatsapp-connector.md` (and a `specs/_index.md` row) when
> `/implement` lands the connector code on `main`. Until then it is the v0
> implementation contract.

A connector implementing `Connector` (see `connector-contract.md`) for WhatsApp
over the first-party Meta Cloud API. Grounded in shipped `kailash.delegate`
(kailash 2.26.2) and the live Meta Cloud API surface, NOT the README/issue prose.

## Responsibilities (mapped to the ABC)

| ABC member                               | WhatsApp behavior                                                                                                                                                                                                                                           |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate(identity, envelope)`       | Resolve the dispatch identity's `delegate_id` to a `Principal` against a `WhatsAppPrincipalResolver` (E.164-keyed + delegate_id-keyed). Unknown identity → disposition per § Unknown-sender below.                                                          |
| `write(action, *, identity, envelope)`   | `action` is a thunk wrapping a **Meta Cloud API `POST /messages`** send. Execute under audit; return `SignedActionEnvelope`. The recipient phone number is PII-redacted before it enters the signed canonical bytes. The send is the auditable side-effect. |
| `read(query, *, identity, envelope)`     | `query` is a thunk that **drains the inbound webhook ingest buffer** (the next verified inbound message[s]). Execute under audit; return `(messages, AttestedReadReceipt)`. The sender phone number is PII-redacted before it enters the manifest.          |
| `invoke(payload, *, identity, envelope)` | Single-method entry: `authenticate` (fail-closed) → template/window pre-flight `Reject` gate → dispatch to send (write); return `ConnectorInvocationResult(payload, audit_events, tenant_id_observed, external_side_effect=True)`.                          |
| `auth_verifier`                          | `Ed25519Verifier(directory)` (shipped concrete).                                                                                                                                                                                                            |
| `ledger`                                 | Protocol-satisfying in-memory `KnowledgeLedger` adapter; records event_type + PII-redacted payload only.                                                                                                                                                    |
| `revocation`                             | Protocol-satisfying `RevocationChannel` adapter (v0: always live).                                                                                                                                                                                          |

## Transport

- **Outbound** — Meta Cloud API: `httpx` `POST https://graph.facebook.com/v{version}/{phone_number_id}/messages`
  with `Authorization: Bearer <token>` and a `{"messaging_product":"whatsapp", "to":"<E.164>", "type":..., ...}`
  body. The send response carries the WhatsApp message id (`wamid...`) and the
  resolved `wa_id`. Credentials + the Graph version + the phone-number-id come from
  `.env` (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_GRAPH_VERSION`)
  — never hardcoded (`security.md`).
- **Inbound** — webhook ingest protocol (no polling equivalent exists): a
  verify-token handshake (echo `hub.challenge` iff `hub.verify_token` matches) +
  an `X-Hub-Signature-256` HMAC check over the raw body (app secret from
  `.env`, `WHATSAPP_APP_SECRET`) + envelope parse (`entry[].changes[].value.messages[]`),
  feeding an in-process ingest buffer the `read` thunk drains. v0 ships the ingest
  protocol + buffer, not a running HTTP server.

## Principal resolution

v0: exact-match lookup of the normalized E.164 phone number against
`WhatsAppPrincipalResolver`. Because the shipped `DelegateIdentity` validates its
ref fields against `^[a-zA-Z0-9_-]+$` (and cannot carry a `+`-prefixed number),
`authenticate` resolves by `delegate_id`; the literal phone number lives on the
message payload. (Alias / group resolution deferred — out of v0 scope.)

## Unknown-sender disposition

`expected` outcomes are the closed enum `{Accept, Reject, EscalateToHuman}`
(conformance). An unknown sender MUST resolve to **`Reject`** in v0 (fail-closed;
not `Accept`), surfaced as `ConnectorAuthenticationError` BEFORE any Cloud API
call on the `invoke` hot path. `EscalateToHuman` reserved for a later policy shard.

## Outbound gating (template + service window)

A free-form message to a recipient outside the open 24-hour customer-service
window MUST resolve to **`Reject`** (`OutsideServiceWindowError`), and a send
naming a template not in the connector's approved-template allowlist MUST resolve
to **`Reject`** (`TemplateNotApprovedError`). Both fire pre-flight, BEFORE any
Cloud API call — never a silent send failure. Meta's own error codes are mapped
as a backstop. An approved-template send is window-exempt.

## v0 out-of-scope

Running HTTP webhook receiver (a Nexus surface is a later shard — never raw
FastAPI/Flask per `framework-first`); durable per-recipient window-state
persistence; third-party aggregator transports (Twilio/Vonage); template
authoring/management; media / interactive / location / contact / sticker
messages; group messaging; encryption beyond transport TLS (E2EE is Meta-handled);
LLM-routed responses (dispatch / kaizen concern); the other connectors.

## Security

- All credentials via `.env` (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
  `WHATSAPP_GRAPH_VERSION`, `WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`,
  `WHATSAPP_PII_HMAC_KEY`, `WHATSAPP_APPROVED_TEMPLATES`); root `.env`
  git-ignored; `.env.example` template only. No secret in logs or audit payloads.
- **Phone-number PII redaction (binding):** phone numbers and `wa_id`s are PII.
  The audit payload (the canonical bytes of every `SignedActionEnvelope` /
  `AttestedReadReceipt`), every ledger record, and every log line MUST carry a
  stable salted-HMAC-SHA256 token (`wa:<first-8-hex>`, keyed by
  `WHATSAPP_PII_HMAC_KEY`), NEVER the raw number. A redaction failure returns the
  grep-able sentinel `<unredactable wa identity>`, never the raw number. The raw
  E.164 lives only in the transient outbound HTTPS body to Meta and is dropped
  after the send.
- **Webhook verification is the security boundary:** an inbound payload whose
  `X-Hub-Signature-256` HMAC does not verify (constant-time compare) is REFUSED
  and never buffered, never audited. The verify-token handshake uses a
  constant-time compare.
- **Commercial-gateway disposition (stated openly):** the connector is
  Apache-2.0 Foundation-owned; the network endpoint is unavoidably commercial
  (Meta Cloud API). This is acceptable and parallels email's commercial SMTP
  host. The shipped code path couples to NO intermediary vendor SDK — the
  transport is a generic `httpx` client against Meta's first-party Graph API; the
  endpoint URL is config, not code.
- Receipts bind FULL dispatch identity (signer/attester `delegate_id` +
  `action_id`/`read_id` + `observed_at`); tamper of any field fails verification.
- Input validation on inbound message fields before they enter the audit path.
