# Spec — Telegram Connector (v0)

Implements `Connector` (see `connector-contract.md`) for Telegram via the Bot
API. Mirrors the email + WhatsApp connectors; differs only in transport
(HTTP-only Bot API — `sendMessage` outbound, `getUpdates` inbound long-poll) and
identity model (integer `user_id` / `chat_id`).

## Responsibilities (mapped to the ABC)

| ABC member                               | Telegram behavior                                                                                                                                                                                                                              |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate(identity, envelope)`       | Resolve the dispatch identity's `delegate_id` to a `Principal` via the dual-keyed resolver (by stringified integer `user_id` and `chat_id`). Unknown identity → `Reject` (fail-closed). A `@username` handle is never a key.                   |
| `write(action, *, identity, envelope)`   | `action` is a thunk wrapping a **`sendMessage` POST**. Execute under audit; return `SignedActionEnvelope`. The send is the auditable external side-effect.                                                                                     |
| `read(query, *, identity, envelope)`     | `query` is a thunk wrapping a **`getUpdates` long-poll**. Execute under audit; return `(updates, AttestedReadReceipt)`. Only update / message ids + count enter the signed manifest — message bodies never enter the audited payload.          |
| `invoke(payload, *, identity, envelope)` | Single-method entry. Authenticate FIRST (fail-closed, before any Bot API send); then dispatch the send via the audited `write` path; return `ConnectorInvocationResult(payload, audit_events, tenant_id_observed, external_side_effect=True)`. |
| `auth_verifier`                          | `Ed25519Verifier(directory)` (shipped concrete).                                                                                                                                                                                               |
| `ledger`                                 | In-memory `KnowledgeLedger` adapter (Protocol-satisfying deterministic adapter; append-only, inspectable). No custom trust primitive.                                                                                                          |
| `revocation`                             | Never-revoked `RevocationChannel` adapter (Protocol-satisfying; v0 has no revocation source wired). No custom trust primitive.                                                                                                                 |

The connector subclasses `Connector` **directly** (ADR-T1) — NOT
`LegacyInvokeConnector`, whose proxied `read` / `write` emit empty, unverifiable
receipts. Every receipt this connector produces is non-empty and verifies under
the shipped `Ed25519Verifier`.

## Transport

- **`sendMessage`** (outbound): `httpx` async POST to
  `{api_base}/bot{token}/sendMessage`. Credentials from `.env`
  (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`) — never hardcoded (`security.md`).
- **`getUpdates`** (inbound): `httpx` async GET long-poll. The `offset` cursor
  advances past consumed updates. The HTTP-level timeout is set just above the
  long-poll seconds so the server can return `[]` cleanly on a quiet poll.
- **429 handling** (ADR-T5): a Bot API `429` raises a typed `RateLimitedError`
  carrying `retry_after` (seconds). The transport never sleeps and never retries
  internally — the caller decides backoff. All other non-2xx responses raise the
  generic `TelegramTransportError` carrying the status + description.
- The bot token is part of every request URL, so the transport NEVER logs the
  URL (or any string derived from the token). Log lines carry the HTTP method +
  the non-secret `chat_id` / `offset` / `count` only.

## Identity model

Telegram integer `user_id` / `chat_id` are the resolver keys, stringified — they
pass the shipped `DelegateIdentity` ref regex `^[a-zA-Z0-9_-]+$` (digits and `-`
are allowed). A `@username` handle is NEVER a resolution key: `@` is ref-unsafe
AND handles are mutable, so a supplied handle resolves to the fail-closed
disposition `Reject`. The resolver is dual-keyed (by `user_id` and `chat_id`),
both views resolving to the same `Principal`.

## Outbound content validation

Every Bot-API-bound field is validated at the `OutboundMessage` construction
boundary (`__post_init__`), so the single boundary covers every send route (the
`invoke` hot path and any direct `write` / `send` call build an `OutboundMessage`
first). A validation failure raises `MessageValidationError` BEFORE any HTTP
request is constructed (ADR-T6):

- `text` rejects an empty value, any disallowed C0/C1 control character (CR,
  NUL, and others; tab and newline are permitted), and a value longer than 4096
  UTF-16 code units (Telegram's length unit — astral characters count as 2).
- `chat_id` accepts an integer (which may be negative for groups / channels) or
  a `@channelusername` handle string; it rejects a `bool`, a non-integer
  non-handle string, and a string with leading / trailing whitespace.

## Receipt identity binding

Both write and read receipts bind their FULL identity (ADR-T3): a write signs
over `{payload, signer_delegate_id, action_id, observed_at}`; a read signs over
`{manifest, attester_delegate_id, read_id, observed_at}`. Two writes with an
identical payload therefore produce DIFFERENT signed bytes (distinct `action_id`

- `observed_at`), closing the replay / forge surface. `verify_action_envelope`
  and `verify_read_receipt` re-derive the signing bytes from the receipt's own
  identity fields, so tampering with any bound field makes verification fail.

## Unknown-sender disposition

`expected` outcomes are the closed enum `{Accept, Reject, EscalateToHuman}`
(conformance). An unknown sender MUST resolve to **`Reject`** in v0 (fail-closed;
not `Accept`). `EscalateToHuman` is reserved for a later policy shard.

## v0 out-of-scope

Webhooks (long-poll only in v0); `@username` resolution; group-topic threading;
media / attachments beyond text; inline keyboards / callback queries; the
dispatch / classification / supervisor spine concerns; the other connectors.

## Security

- All credentials via `.env`; root `.env` git-ignored; `.env.example` template only.
- The bot token is in the request URL — never logged, never in an audit payload.
- No secrets in log lines (method + non-secret `chat_id` / `offset` / `count` only).
- Message-content validation at the construction boundary before any byte transits the network.
