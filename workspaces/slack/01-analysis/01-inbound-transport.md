# 01 — Inbound Transport: Socket Mode vs Events API (read-thunk fit)

> Claim cluster for brief open question #1. Grounded in shipped `kailash.delegate`
> (kailash 2.26.2, introspected via the repo-local `.venv`) + the inherited email
> ADRs. The connector `read` contract is the load-bearing constraint; the Slack
> transport must fit it, not the other way round.

## The constraint that decides this: `read` runs a ONE-SHOT async thunk

The shipped ABC (`connector-contract.md`, verified against the wheel):

```
read(query: Callable[[], Awaitable[T]], *, identity, envelope) -> tuple[T, AttestedReadReceipt]
```

`read` takes a **zero-arg async thunk**, `await`s it ONCE, canonicalizes the
returned value, signs it, and returns `(value, AttestedReadReceipt)`. The audited
seam is exactly one `await query()` per `read` call (verified in the email
reference: `connector.py::read` → `value = await query()` → one receipt). This is
a **request/response** shape: one call in, one bounded result + one receipt out.

A transport that fits `read` must therefore expose a **bounded fetch that returns
and completes** — "give me the messages matching this criterion, then return". A
transport that is a **continuous stream** (a socket that stays open and pushes
events indefinitely) does NOT fit the thunk: there is no natural "the fetch is
done, here is the bounded result" moment, and a single `AttestedReadReceipt` cannot
attest an unbounded, still-growing event stream.

## The two Slack inbound transports

### Socket Mode (WebSocket, persistent)

- The app opens a WebSocket to Slack (`apps.connections.open` → `wss://` URL) and
  Slack PUSHES events (messages, reactions, etc.) over the long-lived socket as
  they happen. No public inbound HTTP endpoint required.
- Shape: **persistent, push, continuous.** The socket stays open for the app's
  lifetime; events arrive asynchronously and indefinitely.
- Credential: an app-level token (`SLACK_APP_TOKEN`, prefix `xapp-`) with
  `connections:write`, distinct from the bot token used for the Web API.

### Events API (webhook, request/response per delivery)

- Slack POSTs each event to a public HTTPS endpoint the app hosts. Each delivery
  is one HTTP request the app must acknowledge with 200 within 3s.
- Shape: **inbound HTTP server required.** Prod-shaped but needs a routable
  endpoint + a request-signature verification (`X-Slack-Signature`).

## Does a persistent socket conflict with the one-shot read thunk? — YES (verdict)

A long-lived Socket-Mode connection is **structurally mismatched** to the `read`
thunk in three ways:

1. **No bounded return.** The socket never "returns a result" — it pushes events
   forever. Wrapping `socket.recv()` in the thunk attests only ONE arbitrary event
   (whichever happened to arrive), not a defined query result. The `given` →
   `behaviour` → `expected` conformance shape (`conformance.md`) presumes a bounded
   action with a defined outcome; "whatever the socket pushed next" is not a
   defined action.
2. **Lifecycle owned by the wrong layer.** A persistent socket is a long-lived
   resource with its own connect/reconnect/backoff/heartbeat lifecycle. The
   connector's `read` is a stateless per-call seam; it does not own a daemon. Per
   `rules/framework-first.md` the long-lived event loop / reconnection daemon is a
   dispatch/runtime concern, NOT a connector-`read` concern — and v0 scope
   explicitly excludes "calling LLM-routed responses inside the connector".
3. **Receipt cardinality.** One `read` call = one `AttestedReadReceipt` over one
   canonical manifest. An open socket produces an unbounded stream of events with
   no single canonical manifest to attest. Forcing one receipt per event would
   require the connector to drive the socket loop — re-introducing the daemon the
   connector must not own.

Socket Mode is the right transport for an **event-driven dispatcher** (a
long-running service that consumes the push stream and invokes the runtime per
event). It is the wrong transport for a **connector `read` primitive**, which is a
bounded, audited, one-shot fetch.

## RECOMMENDATION (resolves open question #1): Web API `conversations.history` fetch for `read`

Implement the `read` path as a **bounded pull** against the Slack Web API
`conversations.history` method (read recent messages from a channel), wrapped in
the zero-arg async thunk — exactly mirroring how the email connector wraps the
bounded IMAP `fetch` in its `read` thunk.

- **Why this fits:** `conversations.history(channel, limit, oldest/latest)` returns
  a **bounded page of messages and completes** — the same request/response shape as
  IMAP `fetch(criteria)`. One call → bounded list → one canonical manifest → one
  `AttestedReadReceipt`. It is the structural twin of `ImapTransport.fetch` (email's
  `read` backing).
- **No daemon, no socket, no public endpoint.** The connector stays a stateless
  per-call seam. Only a bot token (`SLACK_BOT_TOKEN`, `xoxb-`) with
  `channels:history` / `groups:history` is required — symmetric with the email
  outbound path's single-credential model.
- **One credential family for both directions.** Both `read` (history pull) and
  `write` (`chat.postMessage`) use the bot token over the Web API — no second
  app-level token, no socket scope. This collapses the v0 credential surface to one
  `SLACK_BOT_TOKEN`, simpler than email's split SMTP+IMAP creds.

### Cons (honest, per `recommendation-quality.md`)

- **Pull is not real-time.** `conversations.history` reads what already exists; it
  does not deliver events as they happen. For v0 (demonstrate the connector pattern
  generalizes — a bounded audited read), this is correct and sufficient. A
  real-time event consumer is a dispatch-layer concern explicitly out of v0 scope
  (brief § out-of-scope: interactive surfaces, LLM-routed responses).
- **No cursor/pagination loop in v0.** `read` returns one bounded page (default
  limit); deep backfill (cursor pagination across many pages) is deferred. This
  mirrors email's v0 `fetch` returning one search result set without folder/flag
  state. A multi-page cursor loop is a later shard.
- **Socket Mode is genuinely better for a future streaming dispatcher.** This
  recommendation does NOT discard Socket Mode — it scopes it OUT of the connector
  `read` primitive and INTO a future dispatch-layer event consumer. The directory +
  tenant-cascade design below does not block that later addition.

## Transport module shape (mirrors email `imap.py` / `smtp.py`)

- `web_api.py` (or split `outbound.py` + `inbound.py`): pure transport. Builds the
  Web API call (`chat.postMessage` for write, `conversations.history` for read),
  reads credentials ONLY from `SLACK_*` env (typed `SlackConfigError` on absent
  config, never a silent default — mirrors `SmtpConfig.from_env`). No audit logic
  in the transport; the connector wraps the call in the thunk.
- Use the official `slack_sdk` async client (`slack_sdk.web.async_client.AsyncWebClient`)
  — framework-first: do NOT hand-roll an HTTP client (`rules/framework-first.md`:
  raw HTTP clients require nexus-specialist OR a justified SDK client; the vendor
  SDK IS the justified client here). `slack_sdk` is Apache-2.0 (foundation-clean).
  It is a greenfield dependency declared in the connector `pyproject.toml`.

## Citations

- `read`/`write` thunk contract: `specs/connector-contract.md`; reference impl
  `connectors/email/src/delegate_connectors/email/connector.py::read` (one
  `await query()` → one `AttestedReadReceipt`).
- IMAP bounded-fetch twin: `connectors/email/src/delegate_connectors/email/imap.py::ImapTransport.fetch`.
- Conformance behavioural shape (bounded action → defined outcome): `specs/conformance.md`.
- v0 out-of-scope (interactive surfaces, LLM-routed responses): `workspaces/slack/briefs/01-brief.md`.
