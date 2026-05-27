# 02 — Telegram transport: inbound mode + outbound formatting

Telegram is HTTP-only (Bot API). There is no SMTP/IMAP analog: a single bot token
authenticates every call to `https://api.telegram.org/bot<TOKEN>/<method>`. This
doc resolves the two transport deltas the brief flags — inbound mode (open
question #1) and outbound `parse_mode` (open question #3) — against the inherited
audited-thunk contract.

## Outbound (write / invoke): `sendMessage`

The outbound action is a POST to the Bot API `sendMessage` method with
`{chat_id, text, parse_mode?}`. This is the direct analog of the email connector's
SMTP `send` — a pure transport call the connector wraps in a zero-arg async thunk
and runs under audit, producing a `SignedActionEnvelope`.

The connector uses an HTTP client for the call (`httpx` async). Per
`rules/framework-first.md`, this is a transport client, NOT a custom HTTP
SERVER/router/gateway — Nexus owns server-side HTTP; an outbound API client to a
third-party REST endpoint is the permitted primitive (same class as email's
`aiosmtplib`). The transport module holds NO audit logic (mirrors `smtp.py`).

### parse_mode formatting surface (open question #3)

`sendMessage`'s `parse_mode` ∈ `{HTML, MarkdownV2, plain (omit the field)}`. Each
has a DISTINCT escaping surface:

- **plain** (no `parse_mode`): text is sent literally. No escaping needed. Zero
  injection surface from formatting — the safest default.
- **HTML**: must escape `&`, `<`, `>` in user-supplied text segments; only a
  closed tag allowlist (`<b> <i> <u> <s> <a> <code> <pre>`) is interpreted.
- **MarkdownV2**: famously error-prone — 18 reserved characters
  (`_ * [ ] ( ) ~ ` > # + - = | { } . !`) MUST each be backslash-escaped or the
API rejects the whole message with HTTP 400 `can't parse entities`.

The validation boundary is the message-construction dataclass (mirrors email's
`OutboundMessage.__post_init__` + `validate_header_field`): an `OutboundMessage`
equivalent validates `chat_id` and `text` BEFORE any HTTP call fires, so EVERY
send route (the `invoke` hot path and any direct `write`) is covered by one
boundary. The v0 default is **plain** (`parse_mode` omitted) — it carries no
escaping ambiguity and no formatting-injection surface, matching the email v0
posture of "ship the safe minimum, defer the rich surface". HTML / MarkdownV2
escaping is v0 out-of-scope (a later formatting shard), but the boundary still
rejects control characters and enforces Telegram's length limits (text ≤ 4096
UTF-16 code units) so a malformed payload fails closed at construction.

Telegram has NO header-injection analog (no CRLF-delimited headers — the API
takes a JSON body), so the email connector's CRLF/NUL header-injection guard maps
to a Telegram-shaped guard: reject control characters that the Bot API rejects or
that corrupt the JSON body, and enforce `chat_id` is an integer-or-`@channel`
string and `text` is within the length bound.

## Inbound (read): long-polling vs webhook (open question #1)

The brief leans long-polling. Resolving against the read-thunk's ONE-SHOT
semantics:

The inherited `read(query)` contract takes a **zero-arg async thunk** the
connector runs ONCE under audit and attests over the fetched value. The thunk is a
single bounded fetch — it runs, returns a value, the value is canonicalized and
signed into an `AttestedReadReceipt`. It is NOT a long-lived listener.

- **Long-polling** (`getUpdates`): one HTTP GET returns the batch of pending
  updates since the last `offset`. This is a single bounded request-response —
  it maps DIRECTLY onto the one-shot read thunk: the thunk calls `getUpdates`
  once, returns the batch, the connector attests over the message-id manifest.
  No public endpoint, no inbound HTTP server, single bot token. The `offset`
  cursor (acknowledge-by-advancing) is connector state passed into the thunk
  construction, not a server.
- **Webhook** (`setWebhook`): Telegram PUSHES updates to a caller-hosted HTTPS
  endpoint. This requires (a) an inbound HTTP server (a Nexus concern, not a
  connector concern, and explicitly framework-first-blocked here as custom
  server code), and (b) a queue/buffer so the push-driven arrivals can be DRAINED
  by a one-shot read thunk — the read thunk would pop from a buffer the webhook
  handler fills, introducing a two-component design (handler + drain) that does
  NOT fit the single-fetch thunk cleanly.

**Verdict: long-polling for v0.** `getUpdates` is a single bounded
request-response that maps 1:1 onto the one-shot audited read thunk; webhook
requires an inbound HTTP server (framework-first-blocked as custom server code)
plus a queue+drain restructure that breaks the clean one-shot mapping. Long-poll
needs no public endpoint and no server — it is the simplest path that satisfies
the inherited contract. Webhook is v0 out-of-scope (a later transport shard that,
if pursued, would deploy the inbound endpoint via Nexus, not hand-rolled).

## Rate limits (open question #5)

The Bot API enforces ~30 messages/second globally and ~1 message/second per
individual chat (group sends throttled tighter). The transport's posture for v0:

- The transport surfaces the Bot API's `429 Too Many Requests` + its
  `retry_after` field as a typed error (mirrors email's structured `SendResult` /
  raise-on-failure). It does NOT silently swallow 429.
- v0 does NOT encode automatic retry/backoff INSIDE the transport. Rationale:
  retry-under-audit would re-run the audited thunk, producing multiple
  `SignedActionEnvelope`s for one logical send — an audit-chain ambiguity. The
  caller (or a later dispatch-layer policy) owns retry, deciding whether a
  re-send is a new audited action. The transport's job is to surface the 429
  faithfully so the caller can decide. This matches the email v0 boundary (the
  connector raises on transport failure; the caller propagates).

This is a documented v0 boundary, not a stub: the 429 is observed, typed, and
propagated — nothing is hidden (`rules/zero-tolerance.md` Rule 3).

## For Discussion

1. Long-polling's `getUpdates` advances an `offset` cursor to acknowledge
   consumed updates. If the read thunk runs once and attests, but the process
   crashes before persisting the advanced offset, the next read re-fetches the
   same updates — does the receipt's `read_id` + `observed_at` binding make the
   duplicate attestation distinguishable, or is at-least-once delivery a v0
   accepted property?
2. The v0 default is plain text (no `parse_mode`). If a downstream caller wants
   MarkdownV2, where does the escaping responsibility sit — the connector's
   construction boundary, or the caller pre-escaping before `invoke`? Which keeps
   the connector's audit payload honest about what bytes were actually sent?
3. Deferring retry/backoff to the caller means a transient 429 surfaces as a
   failed send. Had retry lived in the transport, the audit chain would carry N
   envelopes for one logical send. Which is the lesser evil for a v0 whose whole
   point is verifiable single-action attestation?
