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

## Wave-1 partial — validation extracted (2026-05-28); transport STILL OPEN

The PURE message-content validation logic was cleanly separable from the
`httpx` transport, so it was extracted in Wave 1 and this todo's remaining
transport work is deferred to Wave 2. Landed in Wave 1 (do NOT re-implement):

- `src/delegate_connectors/telegram/validation.py` — pure (stdlib-only, NO
  `httpx`): `validate_text` (control-char reject — CR/NUL/C0/C1 rejected, tab +
  newline permitted; empty reject; ≤ `MAX_TEXT_UTF16_UNITS` = 4096 UTF-16 code
  units, counting astral chars as 2), `validate_chat_id` (integer-or-`@channel`
  string; `bool` rejected; surrounding-whitespace + malformed-handle rejected),
  and `text_utf16_units`. Raises typed `MessageValidationError(ValueError)`.
- Tier-1 coverage: `tests/unit/test_validation.py` (27 tests) — control-char
  matrix, length bound at/over limit (BMP + emoji), `chat_id` shape matrix.

STILL OPEN for Wave 2 (everything needing `httpx`):

- `transport.py`: `TelegramConfig` (env-loaded creds, typed error if absent,
  never logged), the `httpx` async `send` (`sendMessage` POST) + `get_updates`
  (`getUpdates` long-poll GET), structured `SendResult` / `InboundUpdate`, and
  the `429`/`retry_after` typed `RateLimitedError`.
- The `OutboundMessage` dataclass: its `__post_init__` MUST call the Wave-1
  `validate_text` + `validate_chat_id` so invariant 2 (single boundary covers
  EVERY send route) holds. The validation logic is done; the dataclass wrapper +
  the `httpx` POST that consumes it are the remaining transport work.

This todo is NOT moved to `completed/` — only the validation slice landed.
