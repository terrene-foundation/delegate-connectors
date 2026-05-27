# Todo 02 — SMTP outbound transport

**Implements:** `specs/email-connector.md` § Transport (SMTP)
**Type:** Build · **Capacity:** single shard (~120 LOC, 2 invariants)
**Depends:** 01

## Do

- `src/delegate_connectors/email/smtp.py` — async `send(message) -> SendResult`
  using `aiosmtplib` to the configured host. Pure transport; NO audit logic here
  (the connector wraps this in an audited thunk — todo 05).
- Config from env (`EMAIL_SMTP_*`) via a small config loader; credentials NEVER
  hardcoded (`rules/security.md`).
- Construct a `MIME` message from `(sender, recipient, subject, body)`.

## Invariants

1. Credentials read only from env; absent creds → typed error, not silent default.
2. Returns a structured result (message-id, accepted/rejected) — no bare bool.

## Acceptance

- [ ] Unit test: message construction is correct (Tier-1, no network).
- [ ] No hardcoded host/creds; `grep` clean for literals.
