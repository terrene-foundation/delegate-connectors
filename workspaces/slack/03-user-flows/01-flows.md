# User Flows — Slack Connector (v0)

The connector is a library primitive composed into a `DelegateRuntime`, not a CLI.
"User" here is the application developer wiring the connector. Each flow is the
literal path that developer walks; receipts are what they observe.

## Flow 1 — Compose a Slack runtime

1. Set credentials in `.env`: `SLACK_BOT_TOKEN=xoxb-…` (and, for integration
   tests, `SLACK_API_BASE_URL=http://localhost:<mock-port>`). Never hardcoded.
2. Build the transport + resolver and call `build_slack_runtime(...)`:
   - generate/accept an Ed25519 signing key,
   - register its public key in a `PrincipalDirectory` keyed on `delegate_id`,
   - construct the in-memory `AuditChainEngine`, tenant cascade, dispatch surface,
     and `DelegateRuntime`.
3. Observed outcome: a `ComposedSlackRuntime` handle (runtime + connector +
   verifier + identity). All constructors succeed; the composition passes the
   runtime's R2-composition gate. No network call yet.

## Flow 2 — authenticate (known vs unknown identity)

1. The dispatch surface calls `connector.authenticate(identity, envelope)`.
2. Known `delegate_id` (registered in the resolver) → returns a `Principal`
   (developer sees `Principal(delegate_id, tenant_id, claims={"slack_id": "U…"})`).
3. Unknown `delegate_id` → raises `ConnectorAuthenticationError` (fail-closed
   `Reject`). On the `invoke` hot path this fires BEFORE any `chat.postMessage` —
   the developer observes NO Slack API call for an unknown identity.

## Flow 3 — write / invoke (post a message)

1. Developer calls `await runtime.execute({"channel": "C…", "text": "hello",
"sender": "U…"})` (or drives `connector.invoke(...)` directly).
2. `invoke` authenticates first (Flow 2 gate), then builds an `OutboundSlackMessage`
   — `channel` shape-validated, `text` mrkdwn-escaped at construction. A malformed
   channel id raises `SlackFieldError` before any send.
3. The send runs under the audited `write` path: the `chat.postMessage` thunk is
   awaited once; its result is canonicalized, Ed25519-signed over the FULL receipt
   identity, and returned as a non-empty `SignedActionEnvelope`.
4. Observed outcome: the message arrives in the channel (asserted against the Tier-2
   mock's record, or a live channel in Tier-3); `ConnectorInvocationResult` reports
   `external_side_effect=True`. (Full end-to-end `runtime.execute()` is strict-xfail
   gated on kailash-py#1182 — the per-receipt `write` proof is what ships.)

## Flow 4 — read (fetch channel history)

1. Developer drives `connector.read(query, identity=…, envelope=…)` where `query`
   wraps a `conversations.history(channel, limit)` fetch.
2. `read` awaits the thunk once → a bounded list of `InboundSlackMessage`. It builds
   a canonical manifest (channel + count + message `ts` ids — NO message body in the
   audited payload), signs over the FULL receipt identity, returns
   `(messages, AttestedReadReceipt)`.
3. Observed outcome: the developer gets the messages plus a receipt that verifies
   under the composed `Ed25519Verifier`.

## Flow 5 — receipt verification (the trust payoff)

1. Developer calls `verify_action_envelope(envelope, verifier, observed_at=…)` or
   `verify_read_receipt(receipt, manifest, verifier)`.
2. Returns `True` for an untampered receipt. Tamper any identity field
   (`signer_delegate_id`, `action_id`, `payload`/`manifest`) and the re-derived
   canonical bytes diverge from the signed bytes → verification returns `False`.
3. Observed outcome: the developer can prove a post/read was made by the bound
   identity at the bound time — the connector's reason to exist.
