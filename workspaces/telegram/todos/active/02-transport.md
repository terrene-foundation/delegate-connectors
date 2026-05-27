# Todo 02 — Bot API transport (`sendMessage` + `getUpdates`)

**Implements:** `specs/connector-contract.md` § The interface (zero-arg async thunk)
(+ `02-plans/02-connector-spec.md` § Transport)
**Type:** Build · **Capacity:** single shard (~300 LOC, 4 invariants)
**Depends:** 01

## Do

- `src/delegate_connectors/telegram/transport.py` — `httpx`-backed async transport:
  - `send(message) -> SendResult` — async POST to
    `${TELEGRAM_API_BASE}/bot${TELEGRAM_BOT_TOKEN}/sendMessage` with `{chat_id, text}`.
  - `get_updates(offset) -> list[InboundUpdate]` — async GET long-poll to
    `${TELEGRAM_API_BASE}/bot${TELEGRAM_BOT_TOKEN}/getUpdates` with an `offset` cursor.
  - Pure transport; NO audit logic here (the connector wraps these in audited thunks
    — todo 04).
- `TelegramConfig` loaded from env (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`); absent
  creds → typed error, never a silent default. Token is part of the request URL — the
  transport logs method + chat, NEVER the URL/token.
- `OutboundMessage` dataclass with construction-boundary validation
  (`__post_init__`): control-character reject, `text` ≤ 4096 UTF-16 code units,
  `chat_id` is integer-or-`@channel` string. Validation raised as a typed error
  (e.g. `MessageValidationError`) BEFORE any byte transits the Bot API.
- Structured `SendResult` (message_id, ok, chat_id) and `InboundUpdate`
  (update_id, message_id, chat_id, from_user_id, text) — no bare bools, no raw dicts.
- Bot API `429` + `retry_after` surfaced as a typed transport error
  (e.g. `RateLimitedError`) — NOT swallowed. Retry/backoff is the caller's job (ADR-T5).

## Invariants (4)

1. Credentials read only from env; absent creds → typed error, never a silent default.
   Token/URL NEVER logged.
2. Construction-boundary validation (control-char, length bound, `chat_id` shape)
   covers EVERY send route — `invoke` hot path and any direct `write`/`send` call
   construct an `OutboundMessage` first, so the single boundary covers all of them.
3. `429`/`retry_after` surfaced as a typed error — not swallowed, not retried in-transport.
4. No audit logic in transport (the connector owns the audited thunk wrapping).

## Acceptance

- [ ] Unit: `OutboundMessage` construction rejects CR/LF/NUL/control chars in `text`,
      over-length `text` (> 4096 UTF-16 units), and malformed `chat_id` (Tier-1, no network).
- [ ] Unit: clean `(chat_id, text)` constructs and round-trips to the request body shape.
- [ ] Unit: a `429` response maps to the typed rate-limit error (Tier-1, stubbed at the
      `httpx` boundary only).
- [ ] No hardcoded token/host/base; `grep` clean for literals.
