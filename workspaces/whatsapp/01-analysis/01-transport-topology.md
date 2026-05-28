# Analysis 01 — WhatsApp Transport + Webhook Topology

Grounded in the shipped `kailash.delegate` (kailash 2.26.2, introspected
2026-05-27 via the repo-local venv) and the live Meta Cloud API surface
(verified against Meta for Developers documentation, 2026-05-27). The README
and issue #1035 prose are treated as STALE; every claim below resolves against
either the shipped wheel or the live Meta API.

## The transport question (open question #1 — API choice)

WhatsApp has no SMTP/IMAP equivalent. Outbound is an authenticated HTTPS POST to
a Meta-owned Graph API endpoint; inbound is a Meta-initiated webhook callback.
Three candidate transports were on the table in the brief:

| Option                                 | Production fit                                              | Independence posture                                                                 |
| -------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| **Meta Cloud API** (1st-party)         | `POST graph.facebook.com/v{ver}/{PHONE_NUMBER_ID}/messages` | First-party Graph endpoint. Commercial gateway, but NO intermediary vendor SDK.      |
| On-prem Business API                   | Deprecated by Meta; sunset path                             | Self-hosted, but a dead-end Meta is retiring — not buildable as a durable v0 target. |
| Third-party aggregator (Twilio/Vonage) | Simpler sandbox signup                                      | Couples the SHIPPED code path to a commercial intermediary SDK — fails independence. |

### Verified Meta Cloud API send shape

- **Endpoint**: `POST https://graph.facebook.com/v{version}/{phone_number_id}/messages`
  (current Graph version is in the `v21.x` family as of early 2026; the version
  segment is config-driven, never hardcoded to a single value).
- **Auth**: `Authorization: Bearer <access_token>` header. Production uses a
  permanent System-User token.
- **Body** (JSON): `{ "messaging_product": "whatsapp", "recipient_type": "individual",
"to": "<E.164>", "type": "text", "text": { "body": "..." } }` for a free-form
  text message; `"type": "template"` with a `template` object for a templated send.
- **Response**: carries a `messages[].id` (the WhatsApp message id, `wamid...`) and
  a `contacts[].wa_id` (the resolved WhatsApp user id).

This is a plain HTTPS/JSON call — the natural async client is `httpx` (neither
`httpx` nor `aiohttp` is currently installed in the repo venv; the email
connector uses `aiosmtplib`, so WhatsApp introduces `httpx>=0.27` as a new
declared dependency). Per framework-first, no custom HTTP client/router is
written — `httpx.AsyncClient` is the dumb data-transport layer, exactly as
`aiosmtplib.send` is for email.

## The webhook question (open question #2 — inbound topology)

Inbound is fundamentally different from email's IMAP poll. WhatsApp delivers
inbound messages by calling a consumer-hosted HTTPS endpoint (a webhook). There
is NO polling/fetch API the connector can call to drain a mailbox. The webhook
lifecycle has two phases:

1. **Verification handshake** — Meta issues a `GET` with
   `hub.mode=subscribe`, `hub.verify_token=<shared secret>`, `hub.challenge=<nonce>`;
   the receiver MUST echo the `hub.challenge` iff the verify token matches.
2. **Delivery** — Meta `POST`s a JSON envelope (`entry[].changes[].value.messages[]`)
   for each inbound message, signed with an `X-Hub-Signature-256` HMAC over the
   raw body using the app secret.

### The contract mismatch with `read(query)`

The shipped `Connector.read` signature (introspected) is:

```
read(query: Callable[[], Awaitable[T]], *, identity, envelope) -> tuple[T, AttestedReadReceipt]
```

`read` takes a **zero-arg async thunk** the connector executes ONCE under audit
and attests. That is a pull shape — "go fetch, and I will attest what you
fetched." WhatsApp inbound is push: a message has ALREADY arrived at the webhook
before any `read` is called. The reconciliation is a one-line insight: **the
webhook receiver is an ingest buffer; `read`'s thunk drains that buffer.** The
push event lands the message in an in-process queue; the `read` thunk pops the
next buffered message (or a batch) and the connector attests it exactly as email
attests an IMAP fetch result. The thunk stays one-shot; the buffer absorbs the
push/pull impedance mismatch.

Three sub-options for WHERE the receiver lives were considered:

- **(a) In-process queue + sidecar HTTP receiver the connector drains.** The
  connector owns an `asyncio.Queue`; a receiver protocol hands verified inbound
  messages to `enqueue()`; the `read` thunk calls `dequeue()`. The connector is
  self-contained for the read-attestation path; the HTTP listener is a thin
  protocol the consumer wires (or the repo ships a Nexus-backed reference).
- **(b) Outbound-only connector; inbound is a separate ingest surface.** Matches
  the dispatch/kaizen layering where ingestion is upstream of dispatch. But it
  leaves `read` unimplemented or trivially-stubbed — which the ABC forbids
  (`read` is abstract; a stub violates zero-tolerance Rule 2 and the
  unverifiable-receipt failure that ADR-1 already rejected for the legacy path).
- **(c) Connector defines a webhook-handler protocol; consumers wire it.** The
  connector ships the verification + signature-check + parse logic as a callable
  the consumer mounts on their own HTTP surface; verified messages feed the
  in-process buffer that `read` drains. This is (a) without the connector owning
  the HTTP server.

**v0 ships (a)+(c) composed**: an in-process inbound buffer the `read` thunk
drains, fed by a connector-owned **webhook ingest protocol** (verify-token
handshake + HMAC signature check + envelope parse) that a consumer mounts on a
host HTTP surface. v0 does NOT ship a running HTTP server. If a reference HTTP
receiver is ever added to the repo, framework-first REQUIRES it be a Nexus
surface, not raw FastAPI/Flask — flagged as a GAP for a later shard, NOT v0.

Rationale for not shipping the HTTP server in v0: a live HTTPS endpoint requires
a public TLS-terminated URL reachable by Meta, which is an external-dependency /
deploy concern, not a connector-contract concern. The connector's job is to
turn a verified inbound payload into an `AttestedReadReceipt`; owning the socket
is out of scope. The ingest protocol (handshake + HMAC + parse) IS in scope
because it is the security boundary — an unverified webhook payload must never
reach the audit path.

## Why this is the heaviest channel

- Email: connector owns both transports end-to-end (SMTP socket + IMAP socket).
- WhatsApp: connector owns the outbound HTTPS call fully, but inbound is split —
  the socket is the consumer's/deploy's, the verification + parse + attestation
  is the connector's. The split is the channel's defining structural delta and
  the source of the largest v0 scope-bounding decision.

Sources (verified 2026-05-27):

- Meta for Developers — Cloud API Messages reference (`graph.facebook.com/v{ver}/{PHONE_NUMBER_ID}/messages`, Bearer auth, `messaging_product:"whatsapp"`).
- Meta for Developers — Webhooks messages reference (verify-token handshake, `X-Hub-Signature-256`, `entry[].changes[].value.messages[]`).
