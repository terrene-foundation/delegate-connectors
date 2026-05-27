# Todo 07 — Tier-1 unit tests

**Implements:** `specs/test-infrastructure.md` § Tier 1
**Type:** Test · **Capacity:** single shard
**Depends:** 02–06

## Do

- `connectors/email/tests/unit/` — pure-Python, no I/O. Cover:
  - SMTP message construction (todo 02).
  - IMAP message parsing from a raw fixture (todo 03).
  - Principal resolution: known→Principal, unknown→Reject, normalization (todo 04).
  - Connector ABC compliance (`isinstance`), read/write return non-empty receipts,
    trust properties return concretes (todo 05).
  - `compose` builds a runtime; `execute` returns a result with a signed envelope
    (thunk stubbed at the SDK boundary only — todo 06).

## Acceptance

- [ ] `pytest connectors/email/tests/unit -q` green.
- [ ] No mocks of the `Connector`/runtime contract itself (only the external thunk
      boundary is stubbed at Tier-1).
- [ ] Coverage includes the unknown-sender `Reject` path explicitly.
