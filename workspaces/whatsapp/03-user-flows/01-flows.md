# User Flows — WhatsApp Connector v0

User-facing flows for the WhatsApp connector. "User" here is the developer
composing the connector into a Delegate runtime. Each flow describes what the
user does, what they observe, and the next step. Grounded in shipped kailash
2.26.2 + the Meta Cloud API surface.

## Flow 1 — Authenticate (resolve a WhatsApp identity to a Principal)

1. The user constructs a `WhatsAppPrincipalResolver` from a mapping of known
   E.164 numbers → `Principal`s (the resolver is also keyed by each principal's
   `delegate_id`).
2. The runtime presents a dispatch `DelegateIdentity` to the connector.
3. `authenticate(identity, envelope)` resolves `identity.delegate_id` to a
   `Principal`.
4. **Known identity** → returns the `Principal`; the user proceeds to send/read.
5. **Unknown identity** → raises `ConnectorAuthenticationError` (fail-closed
   `Reject`). No message is constructed, no API call fires. The user sees a typed
   error naming the fail-closed disposition.

What the user observes: either a `Principal` they can act on, or a clear typed
rejection — never a silent `None` and never an outbound call for an unknown
sender.

## Flow 2 — Send a message (invoke / write)

1. The user calls the dispatch hot path (`invoke`) with
   `{sender, to, type, body|template, ...}`.
2. **Gate 1 — authenticate (fail-closed):** unknown identity →
   `ConnectorAuthenticationError` before anything else.
3. **Gate 2 — template/window pre-flight:**
   - Free-form (`type:"text"`) send to a recipient whose 24h customer-service
     window is OPEN → allowed.
   - Free-form send to a recipient whose window is CLOSED →
     `OutsideServiceWindowError` (typed `Reject`) before any API call. The user
     sees: "recipient is outside the 24-hour service window; send a pre-approved
     template instead."
   - Template (`type:"template"`) send naming a template NOT in the approved
     allowlist → `TemplateNotApprovedError` (typed `Reject`) before any API call.
     The user sees: "template '<name>' is not approved; outbound blocked."
   - Template send naming an approved template → allowed (window-exempt).
4. **Send under audit:** the Cloud API `POST /messages` runs inside the audited
   `write` thunk. The recipient phone number is PII-redacted (`wa:<hmac8>`) before
   it enters the signed canonical bytes.
5. The user receives a `ConnectorInvocationResult` (`external_side_effect=True`)
   whose payload carries the Meta `wamid` + resolved `wa_id` — and, as the audited
   side effect, a non-empty `SignedActionEnvelope` that verifies under the
   connector's `Ed25519Verifier`.

What the user observes: a verifiable signed envelope on success, or a clean typed
`Reject` (auth / template / window) BEFORE any external send — never a silent
failure.

## Flow 3 — Receive a message (webhook ingest → read)

1. **Webhook verification (one-time):** Meta issues a `GET` handshake
   (`hub.mode`, `hub.verify_token`, `hub.challenge`). The connector's ingest
   protocol echoes `hub.challenge` iff the verify token matches (constant-time);
   otherwise it refuses. The user wires this protocol onto their own HTTPS surface
   (v0 ships the protocol, not the server).
2. **Inbound delivery:** Meta `POST`s a signed envelope. The ingest protocol
   verifies the `X-Hub-Signature-256` HMAC over the raw body (constant-time); an
   unverified payload is REFUSED and never buffered. A verified inbound message is
   parsed, its sender PII-redacted, the recipient's 24h-window timer reset, and
   the message placed in the in-process ingest buffer.
3. **Read under audit:** the user calls `read(query=...)` where the thunk drains
   the next buffered message(s). The connector attests the drained value and
   returns `(messages, AttestedReadReceipt)`.
4. The user verifies the receipt with `verify_read_receipt(receipt, manifest,
verifier)` → `True` for an untampered receipt; `False` if any identity field
   (attester / read-id / manifest) was tampered.

What the user observes: a verifiable `AttestedReadReceipt` bound to the full
identity (attester + read-id + observed-at), carrying only PII-redacted sender
data — never the raw phone number in the audit record.

## Flow 4 — Verify a receipt (tamper detection)

1. The user holds a `SignedActionEnvelope` (from a send) or `AttestedReadReceipt`
   (from a read).
2. `verify_action_envelope(envelope, verifier, observed_at=...)` /
   `verify_read_receipt(receipt, manifest, verifier)` re-derives the canonical
   signing bytes from the receipt's OWN identity fields and checks (a) byte
   equality AND (b) Ed25519 signature.
3. Untampered → `True`. Tamper of `signer_delegate_id` / `action_id` / `payload`
   (or attester / read-id / manifest) → the re-derived bytes diverge → `False`.

What the user observes: a boolean verdict that is robust to any single-field
tamper, because identity is bound INTO the signed bytes, not asserted alongside
them.

## Flow 5 — Template-not-approved Reject (explicit)

1. The user attempts a template send naming `order_update_v3`.
2. The connector's approved-template allowlist (seeded from
   `WHATSAPP_APPROVED_TEMPLATES`) does NOT contain `order_update_v3` (it is
   `IN_REVIEW` at Meta).
3. The pre-flight gate raises `TemplateNotApprovedError` BEFORE any HTTPS POST.
4. The user sees a typed `Reject` naming the template — actionable: "approve the
   template at Meta, then add it to the allowlist." No message is sent; no silent
   failure; no charge incurred.

## Flow 6 — Compose into a Delegate runtime (e2e)

1. The user builds the spine concretes: `PrincipalDirectory`, `Ed25519Verifier`,
   `AuditChainEngine(chain)`, `TenantScopedCascade`, envelope, identity, signer,
   role.
2. The user constructs `DispatchSurface(whatsapp_connector, signature, envelope,
identity, audit_engine=..., trust_cascade=..., role=..., signer=...,
verifier=...)` and `DelegateRuntime(dispatch_surface=..., audit_engine=...,
cascade=..., envelope=..., identity=..., signer=...)`.
3. The user calls `result = await runtime.execute(input_payload={...})` — note
   `execute` is a COROUTINE; the user MUST `await` it.
4. **v0 status:** the end-to-end `runtime.execute()` outcome assertion is
   strict-xfail pending kailash-py#1182 (an audit-emit signing-bytes bug returns
   `phase=="failed"` on any real verifier). The user observes the composition
   succeeds (no raise on construction); the outcome assertion flips to active when
   #1182 ships.

What the user observes: the connector composes cleanly into the shipped runtime
today; the full audited outcome lands when the upstream SDK fix ships.
