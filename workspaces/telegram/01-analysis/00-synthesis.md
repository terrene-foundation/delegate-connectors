# Analysis Synthesis — Telegram Connector (grounded in shipped kailash 2.26.2)

Reconciles `01-inherited-contract-and-async-discrepancy.md`,
`02-transport-inbound-outbound.md`, `03-identity-model.md`,
`04-test-infrastructure.md`. Every claim is grounded in introspection of the
shipped wheel (`.venv/bin/python`, kailash 2.26.2) — not the README or issue #1035
prose. The Telegram connector is the second pattern-lift after email; the SHARED
SDK ADRs (1–5) are INHERITED and built on, not re-litigated.

## Inherited shared ADRs (re-confirmed, not re-decided)

- **ADR-1** (base class): subclass `Connector` ABC directly; 4 methods + 3
  properties; `read`/`write` take a zero-arg async thunk run under audit;
  `LegacyInvokeConnector` REJECTED.
- **ADR-2** (runtime): `DelegateRuntime` + `DispatchSurface` constructed directly;
  `Delegate.compose` / `delegate.run()` / `pact_engine=` do not exist;
  `execute()` is **async** (re-verified: `iscoroutinefunction is True`).
- **ADR-3** (audit/trust): in-memory `AuditChainEngine(TrustLineageChain)` +
  `Ed25519Verifier(PrincipalDirectory)`; NO Postgres, NO PACT.
- **ADR-4** (conformance): canonical set vendored at
  `tests/fixtures/delegate-conformance/canonical.json` (PR #6); reuse it;
  per-vector + e2e are strict-xfail pending kailash-py#1182.
- **ADR-5** (layout): `connectors/<channel>/`, PEP-420 namespace
  `delegate_connectors.<channel>`, Apache-2.0, `kailash>=2.24.0`, hatchling.

## Channel ADRs (Telegram-specific decisions)

### ADR-T1: Inbound transport is long-polling (`getUpdates`), not webhook

`getUpdates` is a single bounded HTTP request-response that maps 1:1 onto the
inherited one-shot audited read thunk: the thunk calls `getUpdates` once, returns
the update batch, the connector attests over the message-id manifest. Webhook
(`setWebhook`) requires (a) an inbound HTTPS server — a Nexus concern,
framework-first-BLOCKED as hand-rolled server code — and (b) a queue+drain
restructure so push-arrivals can be popped by a one-shot thunk, breaking the clean
single-fetch mapping. Long-polling needs no public endpoint and no server.
Webhook is v0 out-of-scope (a later transport shard that, if pursued, would deploy
the endpoint via Nexus).

### ADR-T2: Outbound is `sendMessage`; v0 default `parse_mode` is plain text

Outbound is a POST to Bot API `sendMessage` with `{chat_id, text}`, wrapped in the
audited write thunk (direct analog of email's SMTP `send`). The HTTP client
(`httpx` async) is a transport client, NOT a custom server (framework-first OK).
`parse_mode` ∈ `{HTML, MarkdownV2, plain}`; v0 ships **plain** (field omitted) —
no escaping ambiguity, no formatting-injection surface. The message-construction
dataclass (`OutboundMessage` analog) validates `chat_id` + `text` at the
construction boundary BEFORE any HTTP call (covers every send route in one place,
mirrors email's `validate_header_field`): reject control characters the Bot API
rejects / that corrupt the JSON body, enforce `text` ≤ 4096 UTF-16 code units,
require `chat_id` be an integer-or-`@channel` string. HTML / MarkdownV2 escaping
is v0 out-of-scope (a later formatting shard).

### ADR-T3: Resolution key is `delegate_id` (ABC contract) + dual `user_id`/`chat_id` view

`authenticate(identity, ...)` resolves by `str(identity.delegate_id)` (inherited
contract). The resolver is ADDITIONALLY dual-keyed by stringified integer
`user_id` AND `chat_id` for transport-side resolution. Re-verified against the
wheel: Telegram's integer ids stringified (`"123456789"`) PASS the
`DelegateIdentity` ref regex `^[a-zA-Z0-9_-]+$` (so they CAN ride on ref fields,
unlike email's `@`-containing address); but `@username` handles are REJECTED
(`@` is ref-unsafe) AND are mutable, so `@handle` is NEVER a resolution key — a
supplied handle resolves to `Reject`. This is email's dual-key pattern with the
channel's two native integer ids replacing email's single address.

### ADR-T4: Tier 2/3 real-infra is a local Bot API HTTP service; live bot is optional

The hermetic, reproducible default is a **local Bot API HTTP service** (an OSS Bot
API surrogate implementing `sendMessage` + `getUpdates`) served via
`docker-compose.yml` — the structural analog of email's Mailpit/GreenMail. It is a
real socket + real JSON cycle the connector's real `httpx` client connects to
(Protocol-satisfying deterministic backend, NOT a Tier-2/3 `@patch` mock). A
live-bot path (Option A — real `TELEGRAM_BOT_TOKEN` + sandbox chat) is documented
as an OPTIONAL secret-gated extra (`requires_live_bot`), skipped by default —
highest-fidelity but non-hermetic. MTProto test server (Option C) is rejected:
wrong protocol layer (user-account, not Bot API; v0 is Bot-API-only).

### ADR-T5: Rate-limit retry/backoff deferred to the caller (v0)

The transport surfaces Bot API `429 Too Many Requests` + `retry_after` as a typed
error; it does NOT silently swallow it (`zero-tolerance.md` Rule 3). v0 does NOT
encode automatic retry INSIDE the transport — retry-under-audit would re-run the
audited thunk and emit multiple `SignedActionEnvelope`s for one logical send (an
audit-chain ambiguity). The caller (or a later dispatch-layer policy) owns retry.
Documented v0 boundary, not a stub.

## Cross-doc staleness note (not a blocker)

`workspaces/email/01-analysis/00-synthesis.md:30` says `execute()` is "sync" —
this is STALE. The shared `specs/runtime-composition.md:38` (corrected in PR #5)
correctly says async, re-confirmed this session against the wheel
(`iscoroutinefunction is True`). The Telegram spec + plan cite the async contract
from `specs/runtime-composition.md`, NOT the stale email synthesis line. The
Telegram connector inherits the async-await call shape email's CODE already uses.

## Inherited blockers (carry forward, do not re-litigate)

- **kailash-py#1182** (SDK audit-emit signature bug): the end-to-end
  `runtime.execute()` assertion + per-vector conformance outcomes are
  strict-xfailed (mirror email). The connector's own `read`/`write` receipts
  verify correctly; the gate is on the runtime, not the connector.
- **#1035 over-specification** (real PACT + real Postgres): aspirational; the
  buildable path is the shipped-API reality (in-memory audit + `Ed25519Verifier`).

## What is fully determined (no NEW blocker)

The connector (`authenticate`/`read`/`write`/`invoke` + 3 trust properties against
the real types), the `httpx`-backed `sendMessage`/`getUpdates` transport, the
dual-keyed resolver, the local Bot API service real-infra tests, the conformance
reuse, and the package layout are ALL buildable now against the shipped API. No
Telegram-specific blocker exists beyond the two inherited from email. Telegram is
the simplest of the three F3 channels (single-token auth, HTTP-only) and validates
that the email pattern generalizes.

## For Discussion

1. Every channel ADR (T1–T5) is a refinement of an inherited shared ADR for the
   HTTP transport. Is there any Telegram decision here that the email pattern did
   NOT already shape, or is Telegram a pure transport-substitution exercise that
   confirms the pattern's generality?
2. The only NEW grounding fact this session produced is "integer ids pass the ref
   regex, `@username` does not" — and it strengthens (not breaks) the email
   dual-key pattern. If the Bot API had keyed identity on `@username` instead of
   integers, would the whole resolution model have inherited email's
   address-mutability fragility?
3. Both inherited blockers (#1182, #1035) are runtime/spec issues, not transport
   issues. Does that mean a future channel (Slack, WhatsApp) inherits the EXACT
   same two blockers, making them properly shared-spec residuals rather than
   per-channel findings?
