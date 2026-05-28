# Todo 05 — Webhook ingest protocol + buffer (HMAC verification boundary)

**Implements:** `specs/connector-contract.md` § Methods (`read` thunk) (+ `02-plans/02-connector-spec.md` § Transport — Inbound, § Security — "Webhook verification is the security boundary")
**Type:** Build (LOAD-BEARING SECURITY) · **Capacity:** single shard (~420 LOC load-bearing, 5 invariants)
**Depends:** 01, 02

**Value-anchor:** delivers the brief acceptance criterion "Inbound message read via webhook returns a signed `AttestedReadReceipt`" — the ingest protocol + buffer the `read` thunk drains (WA-ADR-2). The HMAC + verify-token checks are the security boundary that keeps unverified payloads out of the audit path.

## Do

- `src/delegate_connectors/whatsapp/webhook.py`:
  - Verify-token handshake: echo `hub.challenge` ONLY when `hub.verify_token` matches
    `WHATSAPP_WEBHOOK_VERIFY_TOKEN` under a constant-time compare.
  - `X-Hub-Signature-256` HMAC verification over the RAW request body, app secret from
    `WHATSAPP_APP_SECRET`, constant-time compare. A payload that fails the HMAC is REFUSED
    and NEVER buffered, NEVER audited.
  - Inbound envelope parse: `entry[].changes[].value.messages[]` → normalized
    `InboundMessage` (sender wa_id, type, text body, timestamp). Sender PII redacted
    (todo 02) before the message enters the buffer.
  - In-process `asyncio.Queue` ingest buffer with a one-shot drain the `read` thunk calls.
  - On each verified inbound, feed the per-recipient last-inbound timestamp to the window
    tracker (todo 06) — this is the data source for the 24h-window gate.

## Invariants (5)

1. A payload whose `X-Hub-Signature-256` HMAC does not verify is NEVER buffered.
2. HMAC compare is constant-time (`hmac.compare_digest`), over the raw bytes (not re-serialized).
3. Verify-token compare is constant-time.
4. Sender phone/`wa_id` is PII-redacted (todo 02) before it enters the buffer.
5. The verified inbound feeds the window tracker so the 24h-window gate (todo 06) has data.

## Acceptance

- [ ] Unit (Tier-1): handshake echoes `hub.challenge` on a matching verify-token; rejects
      (no echo) on mismatch.
- [ ] Unit: a body with a tampered/wrong `X-Hub-Signature-256` is refused and never buffered
      (assert the buffer stays empty).
- [ ] Unit: a valid signed payload parses into an `InboundMessage` with the sender redacted
      (raw number absent from the buffered record).
- [ ] Unit: the one-shot `read`-drain returns the next buffered message, then empties.

## Verification

Completed in /implement Wave 1 (2026-05-28).

- `src/delegate_connectors/whatsapp/webhook.py` created:
  `verify_token_challenge` (constant-time `hmac.compare_digest`),
  `verify_signature` (constant-time HMAC over the RAW body bytes, app secret
  from `WHATSAPP_APP_SECRET`), `parse_inbound_envelope`
  (`entry[].changes[].value.messages[]` → `InboundMessage` with the sender
  PII-redacted via todo 02 before any record is built), and `WebhookIngest`
  (verify-then-buffer; in-process FIFO buffer; `drain_one` one-shot drain;
  optional `window_sink` feeding the todo-06 tracker). No running HTTP server
  (WA-ADR-2, out of v0).
- Tier-1 tests `tests/unit/test_webhook.py` — 17 tests, all green:
  - Handshake echoes `hub.challenge` on a matching verify-token; rejects on
    token mismatch and wrong mode.
  - Valid signature accepted; tampered body, wrong secret, missing/malformed
    header all refused.
  - Valid signed payload buffered; `drain_one` returns it then empties the
    buffer; buffered record's sender is redacted (raw number absent).
  - Tampered/missing signature → refused, NOT buffered (buffer stays empty),
    AND does NOT feed the window sink (never audited).
  - Verified inbound feeds the window sink with `(normalized_e164, timestamp)`.
  - Envelope parse extracts text + redacts sender; statuses-only payload → [].
- All 5 invariants hold: HMAC-failing payload never buffered (1); constant-time
  compare over raw bytes (2); constant-time verify-token compare (3); sender
  redacted before buffering (4); verified inbound feeds the window tracker (5).
