# Todo 09 — Tier-1 unit tests

**Implements:** `specs/test-infrastructure.md` § Tier 1 (+ `02-plans/02-connector-spec.md` § Responsibilities — every ABC member)
**Type:** Test · **Capacity:** single shard
**Depends:** 02–08

**Value-anchor:** delivers the brief acceptance criterion "Tier-1 unit suite … green" — the offline coverage that proves every connector member behaves before any infra is required.

## Do

- `connectors/whatsapp/tests/unit/` — pure-Python, no I/O. Cover:
  - Redaction: token stability, sentinel on failure, raw number never present (todo 02).
  - Cloud API request construction + `CloudApiConfigError` on missing env (todo 03).
  - Principal resolution: known→Principal, unknown→Reject, normalization round-trip (todo 04).
  - Webhook: verify-token handshake, HMAC refuse-and-don't-buffer, envelope parse with
    sender redacted, one-shot drain (todo 05).
  - Template/window gate: outside-window→Reject, un-approved-template→Reject, approved→pass,
    in-window free-form→pass, no-send-on-Reject (todo 06).
  - Connector ABC compliance (`isinstance`), read/write non-empty receipts, fail-closed auth,
    trust properties return concretes (todo 07).
  - `compose` builds a runtime; `await execute` returns a result with a signed envelope
    (thunk stubbed at the SDK boundary only — todo 08).

## Acceptance

- [ ] `../../.venv/bin/pytest connectors/whatsapp/tests/unit -q` green.
- [ ] No mocks of the `Connector` / runtime contract itself (only the external thunk boundary
      is stubbed at Tier-1).
- [ ] Coverage explicitly includes the unknown-sender `Reject` path AND both Reject gates.
