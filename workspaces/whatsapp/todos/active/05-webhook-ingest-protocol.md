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
