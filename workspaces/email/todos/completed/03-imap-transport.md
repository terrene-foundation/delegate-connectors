# Todo 03 — IMAP inbound transport

**Implements:** `specs/email-connector.md` § Transport (IMAP)
**Type:** Build · **Capacity:** single shard (~140 LOC, 2 invariants)
**Depends:** 01

## Do

- `src/delegate_connectors/email/imap.py` — async `fetch(criteria) -> list[InboundMessage]`
  using `aioimaplib`/`imaplib` against the configured host. Pure transport; NO audit
  logic (connector wraps in audited thunk — todo 05).
- Parse fetched messages into a normalized `InboundMessage(from_addr, to_addr,
subject, body, message_id, headers)`.
- Config from env (`EMAIL_IMAP_*`); credentials never hardcoded.

## Invariants

1. Credentials read only from env; absent creds → typed error.
2. Inbound fields validated/normalized before return (no raw bytes leaking into the
   audit path downstream).

## Acceptance

- [ ] Unit test: message parsing from a raw IMAP fixture is correct (Tier-1).
- [ ] No hardcoded host/creds.
