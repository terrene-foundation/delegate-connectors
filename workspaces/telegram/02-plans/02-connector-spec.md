# Spec — Telegram Connector (v0)

> **Status: design spec (v0) — not yet implemented.** Per `rules/spec-accuracy.md`
> Rule 5, a spec for unshipped behavior lives in `02-plans/`, not `specs/`. This
> promotes to `specs/telegram-connector.md` (and a `specs/_index.md` row) when
> `/implement` lands the connector code on `main`. Until then it is the v0
> implementation contract.

Implements `Connector` (see `connector-contract.md`) for
Telegram via the Bot API. Mirrors the email connector's shape; differs only in
transport (HTTP-only Bot API) and identity model (integer `user_id`/`chat_id`).

## Responsibilities (mapped to the ABC)

| ABC member                               | Telegram behavior                                                                                                                                                                               |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate(identity, envelope)`       | Resolve the dispatch identity's `delegate_id` to a `Principal` against the dual-keyed resolver. Unknown identity → disposition per § Unknown-sender below.                                      |
| `write(action, *, identity, envelope)`   | `action` is a thunk wrapping a Bot API **`sendMessage`** POST. Execute under audit; return `SignedActionEnvelope`. The send is the auditable external side-effect.                              |
| `read(query, *, identity, envelope)`     | `query` is a thunk wrapping a Bot API **`getUpdates`** long-poll fetch. Execute under audit; return `(updates, AttestedReadReceipt)`.                                                           |
| `invoke(payload, *, identity, envelope)` | Single-method entry: authenticate FIRST (fail-closed), then dispatch to send (write); return `ConnectorInvocationResult(payload, audit_events, tenant_id_observed, external_side_effect=True)`. |
| `auth_verifier`                          | `Ed25519Verifier(directory)` (shipped concrete).                                                                                                                                                |
| `ledger`                                 | Protocol-satisfying in-memory `KnowledgeLedger` adapter (framework-first; no custom trust primitive).                                                                                           |
| `revocation`                             | Protocol-satisfying `RevocationChannel` adapter.                                                                                                                                                |

## Transport

- **Bot API `sendMessage`** (outbound): `httpx` async POST to
  `${TELEGRAM_API_BASE}/bot${TELEGRAM_BOT_TOKEN}/sendMessage` with
  `{chat_id, text}`. Credentials from `.env` (`TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_API_BASE`) — never hardcoded (`security.md`).
- **Bot API `getUpdates`** (inbound): `httpx` async GET long-poll to
  `${TELEGRAM_API_BASE}/bot${TELEGRAM_BOT_TOKEN}/getUpdates` with an `offset`
  cursor. Long-polling (not webhook) — a single bounded request-response that
  matches the one-shot audited read thunk.
- `parse_mode` default is plain text (field omitted). Header-bound-field
  validation has no SMTP analog (the Bot API takes a JSON body): the message is
  validated at the construction boundary — control characters rejected, `text` ≤
  4096 UTF-16 code units, `chat_id` is an integer-or-`@channel` string.
- Rate limits: Bot API `429` + `retry_after` surfaced as a typed transport error;
  retry/backoff is the caller's responsibility.

## Principal resolution

v0: the resolver is dual-keyed by stringified integer `user_id` AND `chat_id`,
plus the `delegate_id` view `authenticate` uses. Telegram's integer ids pass the
shipped `DelegateIdentity` ref regex `^[a-zA-Z0-9_-]+$`; `@username` handles do
not (and are mutable), so a handle is never a resolution key. (Alias / group-topic
resolution deferred — out of v0 scope.)

## Unknown-sender disposition

`expected` outcomes are the closed enum `{Accept, Reject, EscalateToHuman}`
(conformance). An unknown sender MUST resolve to **`Reject`** in v0 (fail-closed;
not `Accept`), surfaced as a typed `ConnectorAuthenticationError` raised BEFORE any
Bot API call fires on the `invoke` hot path. `EscalateToHuman` reserved for a later
policy shard.

## v0 out-of-scope

Webhook inbound (`setWebhook` + inbound HTTP server); HTML / MarkdownV2
`parse_mode` escaping; channels / supergroups / forum topics / inline queries /
callback buttons / inline keyboards; file / media uploads; MTProto (user-account)
integration; payments / Web Apps / Game API; in-transport retry/backoff;
LLM-routed responses (dispatch / classification / supervisor — spine concerns);
the other connectors.

## Security

- All credentials via `.env`; root `.env` git-ignored; `.env.example` template
  only. No `TELEGRAM_BOT_TOKEN` in any log line or audit payload (the token is
  part of the request URL, so the transport logs the method + chat, never the URL).
- No secrets in logs or audit payloads.
- Input validation on the outbound `chat_id` / `text` at the construction boundary
  and on inbound update fields before they enter the audit path.
