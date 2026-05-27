# Analysis Synthesis — Slack Connector (corrected against shipped kailash 2.26.2)

Reconciles `01-inbound-transport.md`, `02-identity-and-injection.md`,
`03-test-infra-topology.md` (2026-05-27). Every claim is grounded in introspection
of the shipped wheel (repo-local `.venv`), NOT the README or issue #1035 prose
(both stale). The Slack connector INHERITS the email connector's shared-SDK ADRs
(subclass `Connector` directly; direct runtime construction; in-memory audit +
`Ed25519Verifier`; vendored conformance fixture; monorepo layout) and builds the
four Slack-specific deltas on top.

## Inherited ADRs (shared spine — NOT re-litigated)

- **ADR-1 (base class):** subclass `kailash.delegate.dispatch.Connector` directly
  (4 methods + 3 properties). NOT `LegacyInvokeConnector` (empty/unverifiable
  receipts; trust properties raise). Re-confirmed against the wheel this session.
- **ADR-2 (runtime):** construct `DispatchSurface` → `DelegateRuntime` directly;
  `Delegate.compose(...)` / `delegate.run()` do not exist. Entry is
  **`await runtime.execute(dict)`** — re-verified ASYNC (coroutine) in 2.26.2.
- **ADR-3 (audit/trust):** in-memory `AuditChainEngine(TrustLineageChain)`;
  `Ed25519Verifier(PrincipalDirectory)`. NO Postgres, NO PACT.
- **ADR-4 (conformance):** REUSE the vendored
  `tests/fixtures/delegate-conformance/canonical.json` (5 vectors, DV-3/5/7/9/10).
  Per-vector execution + e2e are strict-xfail pending kailash-py#1182 — mirror
  email's exact treatment.
- **ADR-5 (layout):** `connectors/slack/`, dist `delegate-connector-slack`,
  namespace `delegate_connectors.slack` (PEP 420), Apache-2.0, `kailash>=2.24.0`,
  hatchling.

## Slack-specific ADRs (the four deltas)

### ADR-S1: `read` = bounded Web API `conversations.history` pull — NOT Socket Mode

A long-lived Socket-Mode WebSocket **structurally conflicts** with the connector
`read` thunk's one-shot semantics (`read` awaits a zero-arg async thunk ONCE and
returns one bounded value + one `AttestedReadReceipt`). A persistent socket has (a)
no bounded "the fetch is done" return, (b) a connect/reconnect/heartbeat lifecycle
the stateless connector must not own, and (c) no single canonical manifest for one
receipt to attest. **Verdict: Socket Mode is the right transport for a future
streaming dispatcher, the WRONG transport for the connector `read` primitive.**

The `read` path is a **bounded pull** against `conversations.history(channel,
limit)` wrapped in the thunk — the structural twin of email's IMAP `fetch(criteria)`
backing `read`. One credential family (`SLACK_BOT_TOKEN`, `xoxb-`) covers BOTH
`read` (history) and `write` (`chat.postMessage`) — simpler than email's split
SMTP+IMAP creds. Cons: pull is not real-time (correct for v0; real-time is a
dispatch-layer concern out of v0 scope); no cursor-pagination loop in v0 (one
bounded page, mirrors email's single search result set).

### ADR-S2: dual-keyed resolver, `delegate_id` primary, Slack id literal secondary

Slack ids (`U…`/`C…`/`W…`/`G…`/`D…`) PASS the `DelegateIdentity` ref-field regex
`^[a-zA-Z0-9_-]+$` (verified this session) — a clean delta from email, whose `@`/`.`
addresses are REJECTED. Despite that, the dispatch resolution key stays
**`delegate_id`** (primary) for cross-connector uniformity (same `authenticate`
shape as email) and stability across handle/workspace changes. `SlackPrincipalResolver`
mirrors `EmailPrincipalResolver`: a `by_delegate_id` index (primary, drives
`authenticate`) + a `by_slack_id` index (secondary literal, drives payload
attribution). Unknown `delegate_id` → fail-closed `ConnectorAuthenticationError`
(closed-enum `Reject`). `normalize_slack_id` is shape-validate + trim only (NOT
lowercase — Slack ids are case-significant, unlike email). The team/workspace id
lives in `Principal.claims` for forward-compat with multi-workspace OAuth (later
shard) without entering the v0 lookup key.

### ADR-S3: injection boundary = id-validation + mrkdwn-escaping at `OutboundSlackMessage` construction

Slack's `chat.postMessage` is a JSON Web API call, so email's CRLF header-injection
vector does NOT apply. The Slack surfaces are: (1) channel/id-field injection →
validate every id-bound field with `normalize_slack_id` shape-validation (typed
`SlackFieldError`); (2) mrkdwn injection → escape `&`/`<`/`>` in user-controlled
`text` per Slack's documented escaping contract so injected `<@U…>` / `<!channel>` /
`<url|label>` cannot go live; (3) Block Kit structural JSON injection → **removed
entirely for v0** by keeping `blocks`/`attachments` OUT of scope (baseline text
only, per brief § out-of-scope). The single validation boundary is
`OutboundSlackMessage.__post_init__` — every send route (the `invoke` hot path and
any direct `write`) builds it first, identical in placement to email's
`OutboundMessage.__post_init__`. Cons: escaping changes what the user sees for
literal `<`/`>`/`&`; no rich formatting in v0 (acceptable — v1 Block Kit concern).

### ADR-S4: Tier-2 = single Web API mock-server container (CI-runnable); Tier-3 = opt-in live workspace

Slack has no self-hostable real server. Mirroring email's "single reproducible
container, no boundary mocking" standard: **Tier 2** uses ONE Web API mock-server
container serving `chat.postMessage` (records + returns `ts`) and
`conversations.history` (returns recorded messages); the connector talks to it via a
real `AsyncWebClient(base_url=...)` — NO mocking at the connector boundary (the
_server_ is a local stub, exactly as Mailpit is a local SMTP server). Round-trip =
post → history-read through the connector's `read` path → verify the identity-bound
`AttestedReadReceipt`. **Tier 3** = opt-in live workspace + test bot token behind a
`requires_live_slack` skip-gate (mirrors email's `requires_greenmail`). Live
workspace as Tier-2 is REJECTED: it fails the "CI-runnable without manual per-job
setup" bar (provisioned workspace + per-job secret + rate-limit flakiness). The
stale Node `slack-mock` is NOT used as-is (`rules/dependencies.md` — unmaintained);
the container serves the two Web API methods v0 uses (WireMock/Prism-seeded or a
small purpose-built stub).

## Inherited blocker (NOT a Slack-new gap)

- **kailash-py#1182 gates end-to-end `runtime.execute()`** — the SDK audit-emit
  signs payload bytes while `AuditChainEngine` verifies full-entry bytes →
  `execute()` returns `phase=="failed"` under any real verifier. SDK bug, not
  connector bug; the connector's OWN `read`/`write` receipts verify correctly.
  Mirror email: composition + per-receipt verification ship NOW; e2e is strict-xfail
  pending #1182. (`specs/conformance.md`, `workspaces/email/journal/0005`.)

## Brief corrections (GATE before /todos)

| Brief / README claim                                           | Shipped reality (kailash 2.26.2)                                                                                             | Verdict                                                                                  |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Default lean: Socket Mode for `read` (brief § v0 scope item 3) | Socket Mode conflicts with the one-shot `read` thunk; v0 `read` is a bounded `conversations.history` pull (ADR-S1).          | CORRECTED — brief's "unless /analyze identifies a structural issue" escape clause fires. |
| `runtime.execute()` "synchronous" (email cluster docs 02/03)   | `execute()` is an ASYNC coroutine in 2.26.2 (re-verified); `specs/runtime-composition.md` PR-#5 correction is authoritative. | CORRECTED (inherited)                                                                    |
| #1035 "real PACT + real Postgres"                              | No PACT engine arg, no Postgres backend; audit is in-memory. Aspirational.                                                   | FALSE (inherited from email BLOCKER-2)                                                   |
| README `connect()/identify()/normalize()`                      | Real ABC = `authenticate/invoke/read/write` + 3 properties.                                                                  | CONFIRMED-stale (inherited)                                                              |
| `slack-mock` (open source) for Tier-2 (brief § open Q4)        | Original Node `slack-mock` is stale/unmaintained; use a current-API single-container stub instead (ADR-S4).                  | CORRECTED                                                                                |

## What IS fully determined (buildable now)

The `SlackConnector` (`authenticate`/`read`/`write`/`invoke` + 3 trust properties
against the real types), `build_slack_runtime` composition, the dual-keyed resolver,
the `OutboundSlackMessage` injection boundary, the mock-server Tier-2 topology, the
conformance-set reuse, and the package layout are all buildable now against the
shipped API. Only the end-to-end `execute()` assertion + per-vector conformance
outcome are strict-xfail gated on #1182 (inherited, not Slack-new).
