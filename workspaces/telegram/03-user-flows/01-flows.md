# User Flows — Telegram Connector (v0)

The user-facing paths a connector author / integrator walks. Each flow is the
literal sequence an operator performs and the observable outcome they see. These
are the walks to verify before declaring any shard "done"
(`rules/user-flow-validation.md`).

## Flow 1 — Configure credentials

1. Copy `.env.example` → `.env` and fill `TELEGRAM_BOT_TOKEN` (from `@BotFather`),
   `TELEGRAM_API_BASE` (defaults to `https://api.telegram.org`; point at the local
   Bot API service in tests), and for the optional live path
   `TELEGRAM_TEST_CHAT_ID`.
2. The transport reads creds ONLY from the environment. If a required var is
   absent, construction raises a typed config error — never a silent default.

   Observable: missing `TELEGRAM_BOT_TOKEN` → typed error naming the var; nothing
   proceeds. No credential ever appears in a log line or audit payload.

## Flow 2 — Authenticate (resolve identity → Principal)

1. The integrator constructs a dual-keyed resolver mapping known
   `user_id`/`chat_id`/`delegate_id` → `Principal`.
2. `await connector.authenticate(identity, envelope)`:
   - Known dispatch identity → returns a `Principal`.
   - Unknown identity (or a `@username` handle, which never resolves) →
     `ConnectorAuthenticationError` (the closed-enum `Reject`, fail-closed).

   Observable: a known id surfaces a `Principal`; an unknown id surfaces a typed
   Reject error — the integrator sees fail-closed behavior, not a silent `None`.

## Flow 3 — Send a message (invoke / write)

1. `await connector.invoke({"chat_id": ..., "text": "..."}, identity=..., envelope=...)`.
2. Internally: `authenticate` runs FIRST (fail-closed gate) — an unknown identity
   raises BEFORE any Bot API call fires; no `sendMessage` is sent.
3. On a known identity: the message is constructed (validated at the boundary:
   control chars rejected, text ≤ 4096 UTF-16 units, `chat_id` shape checked),
   the audited `write` thunk POSTs `sendMessage`, and a `SignedActionEnvelope`
   comes back.

   Observable: the message arrives at the destination chat; the call returns a
   `ConnectorInvocationResult(external_side_effect=True)` whose underlying
   `SignedActionEnvelope` verifies under the connector's `Ed25519Verifier`.

## Flow 4 — Read inbound messages (read / long-poll)

1. The integrator builds a one-shot `getUpdates` thunk (carrying the current
   `offset`).
2. `value, receipt = await connector.read(query, identity=..., envelope=...)`:
   the thunk calls `getUpdates` once, returns the update batch; the connector
   attests over the message-id manifest (no message bodies enter the audit
   payload).

   Observable: the integrator receives the updates AND a non-empty
   `AttestedReadReceipt`.

## Flow 5 — Verify a receipt

1. `verify_action_envelope(envelope, verifier, observed_at=...)` for a write;
   `verify_read_receipt(receipt, manifest, verifier)` for a read.
2. Tamper with ANY bound field (signer, action_id/read_id, payload/manifest,
   observed_at) → verification returns `False`.

   Observable: an untampered receipt verifies `True`; any single-field tamper
   fails verification — the FULL identity binding is demonstrable.

## Flow 6 — Run the real-infra tests

1. `docker compose up` brings up the local Bot API HTTP service.
2. `.venv/bin/python -m pytest connectors/telegram/tests/` (or `uv run pytest`).

   Observable: Tier-1 unit suite green; Tier-2/3 integration green against the
   local service (outbound arrival + inbound round-trip); the e2e
   `runtime.execute()` test reports xfail (gated on kailash-py#1182, inherited);
   conformance well-formedness + ABC-composition green, per-vector outcomes xfail
   (same gate). When the local service is unreachable, integration tests skip with
   a "cannot execute" reason — never a false green.

## For Discussion

1. Flow 3 asserts the message "arrives at the destination chat." On the hermetic
   local Bot API service the assertion is against the service's stored-message
   endpoint; on the live-bot path it is a real chat. Which walk is the canonical
   "done" gate for the send flow, and does the hermetic walk fully exercise the
   user's experience?
2. Flow 4's read thunk advances an `offset`. If the integrator forgets to persist
   the advanced offset between reads, Flow 4 re-returns the same updates. Should
   the v0 user flow surface offset-management as the integrator's responsibility,
   or does the connector hide it?
3. Flow 6's e2e xfail is inherited, not Telegram-specific. Does an integrator
   reading "xfail" understand it as "the connector works; the SDK runtime has a
   known bug," or could it read as "the connector is incomplete"? What in the test
   output makes that distinction legible?
