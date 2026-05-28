# 04 — Test infrastructure topology

Resolves open question #4 (test-infra topology) against the inherited real-infra
preference (`specs/test-infrastructure.md`: Tier 2/3 use REAL infrastructure, no
mocks at the boundary) and the conformance harness already vendored (ADR-4).

## The constraint

The email connector reaches a real SMTP/IMAP surface via containers (Mailpit +
GreenMail) — no live external account, no credentials in CI, fully reproducible.
Telegram's Bot API is HTTP-only and hosted by Telegram; the three candidate
real-infra topologies are:

| Option                                | What it is                                                                              | Reproducible in CI?                                                                                                   | Verdict                                      |
| ------------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| A. Live test bot + sandbox chat       | Real `@BotFather` token talking to a sandbox group                                      | Requires a live `TELEGRAM_BOT_TOKEN` + chat id as CI secrets; rate-limited; non-hermetic (depends on Telegram uptime) | NOT the default — non-hermetic, secret-bound |
| B. Local mocked Bot API HTTP endpoint | A container/process serving the Bot API surface (`sendMessage`, `getUpdates`) over HTTP | Hermetic, no secrets, reproducible                                                                                    | **DEFAULT for Tier 2/3**                     |
| C. Local MTProto test server          | Telegram's MTProto test DC                                                              | MTProto is the user-account protocol, NOT the Bot API; v0 is Bot-API-only; heavy JVM/native setup                     | Out of scope — wrong protocol layer          |

## Does an OSS mocked Bot API server exist? (open question #4)

Yes — the Bot API is plain HTTP+JSON, and there are open-source local Bot API
surrogates. The most direct is **`telegram-bot-api`**, the official
`tdlib/telegram-bot-api` server, which is open source (it is the same server
Telegram runs, runnable locally) and can be pointed at the test DC; and lighter
OSS mock-servers (e.g. a small HTTP service implementing `sendMessage` +
`getUpdates` responses) exist. For a v0 that needs only `sendMessage` (outbound
arrival assertion) and `getUpdates` (inbound round-trip), the lightest hermetic
option is a **local HTTP service that implements the two Bot API methods** the
connector calls — served as a container in `docker-compose.yml`, the direct
structural analog of email's Mailpit/GreenMail services.

This is NOT a Tier-1 mock (a `@patch`/`MagicMock` of the HTTP client — BLOCKED in
Tier 2/3 per `rules/testing.md`). It is a real HTTP endpoint the connector's real
`httpx` client connects to over a real socket, with a real JSON request/response
cycle — the boundary is real. It is a Protocol-satisfying deterministic backend
(the same exemption email uses for its in-memory ledger): real transport, real
socket, deterministic stored state, inspectable via a search endpoint (analog of
Mailpit's REST arrival assertion).

## Decided topology

- **Tier 1 (unit):** pure-Python, no I/O. The outbound `sendMessage` thunk and
  inbound `getUpdates` thunk are stubbed at the SDK-boundary (the thunk itself),
  not the connector contract. Covers: principal resolution
  (`user_id`/`chat_id`/`delegate_id`), unknown-identity → `Reject`,
  message-construction validation (control chars, length bound), receipt
  identity-binding + tamper-fail. Mirrors email's Tier-1 exactly.
- **Tier 2/3 (integration / e2e) — real infra:**
  - `docker-compose.yml` runs a **local Bot API HTTP service** (the hermetic
    surrogate) on a fixed port. Reachability gate in
    `tests/integration/_botapi.py` (`requires_botapi`) skips with a "cannot
    execute" reason when unreachable — mirrors email's `requires_mailpit_smtp` /
    `requires_greenmail`.
  - **Outbound:** the connector's `invoke` → audited `write` → `sendMessage`
    POST to the local Bot API service; assert the message arrived via the
    service's stored-message inspection endpoint AND a verifiable
    `SignedActionEnvelope` came back.
  - **Inbound round-trip:** seed an update into the local service → the read
    thunk calls `getUpdates` through the connector's `read` path → assert a
    verifiable, identity-bound `AttestedReadReceipt`.
  - **Audit chain:** in-memory `AuditChainEngine(chain)` — NO Postgres container
    (inherited ADR-3).
  - **Trust verify:** real `Ed25519Verifier(PrincipalDirectory(...))` — NOT
    `NullVerifier` (inherited).
  - **e2e:** compose a `DelegateRuntime` with the `TelegramConnector` →
    `await runtime.execute(...)` → a `sendMessage` fires at the local service.
    This end-to-end `execute()` assertion is **xfail-gated on the SAME SDK
    audit-emit bug** the email connector hit (`workspaces/email/journal/0005` /
    kailash-py#1182) — the runtime's `_emit_phase_audit` signs payload bytes
    while `AuditChainEngine.emit_event` verifies full-entry signing bytes, so
    `execute()` returns `phase=="failed"` under any real verifier. The connector's
    OWN `read`/`write` receipts verify correctly (proven in Tier-1) — the gate is
    on the runtime, not the connector. Mirror email's exact treatment.
- **Live-bot path (Option A):** documented as an OPTIONAL, secret-gated extra
  (a `requires_live_bot` gate keyed on `TELEGRAM_BOT_TOKEN` + a sandbox
  `TELEGRAM_TEST_CHAT_ID`), skipped by default. It is the highest-fidelity check
  but non-hermetic; the hermetic local service is the reproducible default that
  CI runs.

## Conformance (inherited ADR-4 — reuse, do not re-source)

The canonical conformance vector set is ALREADY vendored at
`tests/fixtures/delegate-conformance/canonical.json` (monorepo root, PR #6; 5
vectors DV-3/5/7/9/10, 4 Reject + 1 Accept). The Telegram connector REUSES it via
the same `conformance` marker pattern as email — a local loader re-hydrates the
records into typed `ConformanceVector` instances; the well-formedness gate + ABC
composition harness run now; per-vector outcome assertion is strict-xfail pending
kailash-py#1182. Do NOT re-source from kailash-py (cross-repo read, BLOCKED).
Mirror email's `tests/conformance/` exactly.

## For Discussion

1. The local Bot API HTTP service is a real socket but deterministic stored state
   — it satisfies the Protocol-adapter exemption. Where is the line between "real
   infra" (Mailpit is a real SMTP server) and "deterministic surrogate" (a small
   service implementing two methods), and does the Telegram surrogate sit on the
   acceptable side because the transport boundary (socket + JSON) is genuinely
   exercised?
2. The live-bot path is highest-fidelity but non-hermetic and secret-bound. If CI
   only ever runs the hermetic surrogate, what class of bug (Bot API quirk, real
   rate-limit behavior, real `retry_after`) could the surrogate miss that only the
   live bot would catch — and is that acceptable for a v0?
3. The e2e `execute()` xfail is inherited from the SAME SDK bug email hit. If
   kailash-py#1182 lands while the Telegram connector is mid-build, do the
   Telegram per-vector xfails flip to XPASS in lockstep with email's, or does each
   connector's xfail un-gate independently?
