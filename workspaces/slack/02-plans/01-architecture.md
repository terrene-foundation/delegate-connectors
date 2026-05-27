# Implementation Architecture — Slack Connector (v0)

Grounded in `01-analysis/00-synthesis.md`. Inherits the email connector's shared
spine ADRs (1–5); adds the four Slack deltas (S1–S4). Every symbol cited resolves
against shipped kailash 2.26.2 OR is a new connector symbol defined here.

## ADRs (decided)

| ADR               | Decision                                                                                                           | Rationale (1-line)                                                                                                         |
| ----------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| ADR-1 (inherited) | Subclass `Connector` directly                                                                                      | Legacy path's receipts are empty/unverifiable; trust props raise.                                                          |
| ADR-2 (inherited) | Direct `DispatchSurface`→`DelegateRuntime`; `await runtime.execute(dict)`                                          | No `compose()`/`run()`; `execute` is async in 2.26.2 (re-verified).                                                        |
| ADR-3 (inherited) | In-memory `AuditChainEngine` + `Ed25519Verifier`                                                                   | No PACT, no Postgres in the shipped runtime.                                                                               |
| ADR-4 (inherited) | Reuse vendored `canonical.json`; per-vector + e2e strict-xfail                                                     | #1182 gates outcome assertion; mirror email.                                                                               |
| ADR-5 (inherited) | `connectors/slack/`, `delegate-connector-slack`, `delegate_connectors.slack`                                       | Per `specs/monorepo-layout.md`.                                                                                            |
| **ADR-S1**        | `read` = bounded `conversations.history` pull; Socket Mode rejected                                                | Persistent socket conflicts with the one-shot `read` thunk (no bounded return, owns a daemon, no single receipt manifest). |
| **ADR-S2**        | Dual-keyed resolver, `delegate_id` primary + Slack-id literal                                                      | Slack ids pass the ref regex but `delegate_id` keeps `authenticate` uniform + stable; mirrors email.                       |
| **ADR-S3**        | Injection boundary at `OutboundSlackMessage.__post_init__`: id shape-validate + mrkdwn-escape; Block Kit out of v0 | JSON API → no CRLF vector; the surfaces are id-redirect + mrkdwn + structural JSON (last removed by scoping blocks out).   |
| **ADR-S4**        | Tier-2 = single Web API mock-server container; Tier-3 = opt-in live workspace                                      | Slack has no self-hostable server; mock container is the CI-runnable Mailpit analogue.                                     |

## Connector ABC-member mapping (the 7 abstracts)

| ABC member                                     | Slack behavior                                                                                                                                                                                                                                                                                               |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `authenticate(identity, envelope)`             | Resolve `identity.delegate_id` against `SlackPrincipalResolver` (by_delegate_id index). Unknown → `ConnectorAuthenticationError` (fail-closed `Reject`).                                                                                                                                                     |
| `write(action, *, identity, envelope)`         | `action` is a thunk wrapping a `chat.postMessage`. Run under audit; canonicalize the post result, Ed25519-sign over FULL identity (payload + signer_delegate_id + action_id + observed_at), return non-empty `SignedActionEnvelope`.                                                                         |
| `read(query, *, identity, envelope)`           | `query` is a thunk wrapping a `conversations.history` fetch. Run under audit; build a canonical manifest (channel + message count + message `ts` ids — NO message body bytes in the audited payload, mirroring email's `_read_manifest`), sign over FULL identity, return `(messages, AttestedReadReceipt)`. |
| `invoke(input_payload, *, identity, envelope)` | Hot-path entry. `authenticate` FIRST (fail-closed gate before any Slack API call), then build `OutboundSlackMessage` (id-validate + text-escape), send via the audited `write` path, return `ConnectorInvocationResult(payload, audit_events, tenant_id_observed, external_side_effect=True)`.               |
| `auth_verifier`                                | The supplied `Ed25519Verifier` (shipped concrete).                                                                                                                                                                                                                                                           |
| `ledger`                                       | `InMemoryKnowledgeLedger` (Protocol-satisfying deterministic adapter — same as email; the SDK ships only the Protocol).                                                                                                                                                                                      |
| `revocation`                                   | `NeverRevokedChannel` (Protocol-satisfying; v0 has no revocation source).                                                                                                                                                                                                                                    |

Class metadata: `connector_id = "delegate-connector-slack"`, `connector_kind =
"slack"`, `requires_capabilities = frozenset({"slack.post"})`.

## Receipt identity-binding (inherited, mandatory)

Both receipts bind FULL identity into signing bytes (`signer`/`attester` +
`action_id`/`read_id` + `observed_at`), NOT the bare payload — so two identical
posts produce different signed bytes and tamper of any identity field fails
verification. Reuse email's `build_action_signing_bytes` / `build_read_signing_bytes`
/ `verify_action_envelope` / `verify_read_receipt` shapes (these are connector-local
helpers, re-implemented per-connector; the canonical-json signing contract is
shared via `kailash.trust._json.canonical_json_dumps`).

## Shard breakdown (sized per `rules/autonomous-execution.md` § Per-Session Capacity Budget)

Each shard ≤500 LOC load-bearing logic, ≤5–10 invariants, ≤3–4 call-graph hops,
describable in ≤3 sentences. Boilerplate-heavy shards may run larger (single
pattern stamped out). Shards 1–6 each carry a value-anchor tied to a brief
acceptance criterion.

- **Shard 1 — Package scaffold.** Create `connectors/slack/` package shape
  (`pyproject.toml`, namespace dir, SPDX headers, `slack_sdk` + `kailash>=2.24.0`
  deps). Mostly boilerplate, single pattern. _Value-anchor:_ brief acceptance
  "package shape matches monorepo-layout.md". Invariants: 2 (namespace PEP-420,
  SPDX every file).

- **Shard 2 — Web API transport (`web_api.py`).** `SlackWebConfig.from_env`
  (`SLACK_BOT_TOKEN`, optional `SLACK_API_BASE_URL` for the mock), `SlackTransport`
  wrapping `AsyncWebClient` with `post_message(OutboundSlackMessage) -> PostResult`
  and `history(channel, limit) -> list[InboundSlackMessage]`. Pure transport, no
  audit logic. _Value-anchor:_ brief acceptance "outbound post verified to arrive"
  - "inbound read via history". ~300 LOC, invariants: 4 (env-only creds, no creds
    logged, typed config error, base_url override for mock).

- **Shard 3 — Injection boundary + message types.** `OutboundSlackMessage` (frozen,
  `__post_init__` id-validate + text-escape), `InboundSlackMessage`,
  `normalize_slack_id`, `SlackFieldError`, mrkdwn-escape helper. _Value-anchor:_
  brief acceptance "header-injection defenses at message-construction boundary".
  ~250 LOC load-bearing, invariants: 5 (id shape regex, mrkdwn `&<>` escape, every
  send route builds it first, typed error, no Block Kit surface).

- **Shard 4 — Principal resolver (`directory.py`).** `SlackPrincipalResolver`
  (dual-keyed: by_delegate_id + by_slack_id), `UnknownSenderDisposition` (closed
  enum), `ResolutionOutcome`. _Value-anchor:_ brief acceptance "authenticate
  resolves known identity; unknown → fail-closed Reject BEFORE any Slack API call".
  ~150 LOC, invariants: 3 (delegate_id primary, fail-closed Reject, case-significant
  normalize).

- **Shard 5 — Connector (`connector.py`).** `SlackConnector(Connector)` — the 4
  primitives + 3 trust properties + receipt-binding helpers + `InMemoryKnowledgeLedger`
  - `NeverRevokedChannel`. The load-bearing shard. _Value-anchor:_ brief acceptance
    "SlackConnector satisfies the ABC; receipts verify; unknown-sender Reject on the
    invoke hot path; receipts bind full identity". ~400 LOC, invariants: ~7 (ABC
    instantiation succeeds, authenticate-first gate, full-identity binding, non-empty
    receipts, ledger never carries creds, tenant echo, fail-closed Reject). At the
    upper budget — has a live feedback loop (Tier-1 unit suite), so within the
    feedback-loop multiplier.

- **Shard 6 — Runtime composition (`compose.py`).** `build_slack_runtime(...)`,
  `SlackV0Signature`, `ComposedSlackRuntime`. Mechanical mirror of email's
  `compose.py` (Ed25519 directory + in-memory audit + cascade + dispatch surface +
  runtime). _Value-anchor:_ brief acceptance "inbound read returns a signed receipt
  that verifies under Ed25519Verifier" (composition half). ~200 LOC, invariants: 4
  (real verifier not Null, identity registered, cascade root grant proof, async
  execute wiring).

- **Shard 7 — Tier-1 unit suite.** Unit tests for the 4 primitives, resolver,
  injection boundary, receipt binding/tamper. Offline, thunk stubbed at the
  SDK-boundary only. Boilerplate-heavy (one pattern per test). _Value-anchor:_
  brief acceptance "Tier-1 unit suite green" + "tamper of any field fails
  verification" (regression tests). Invariants tracked per test.

- **Shard 8 — Tier-2 mock-server integration + docker-compose.**
  `docker-compose.yml` (Web API mock service), `tests/integration/_slack_mock.py`
  reachability gates, post→history round-trip test asserting verifiable
  `AttestedReadReceipt`. _Value-anchor:_ brief acceptance "Tier-2/3 real-infra
  suite green" + "outbound post verified to arrive (real-infra, not mocked
  client)". Invariants: 3 (real AsyncWebClient against mock, skip-gate when
  unreachable, round-trip receipt verifies).

- **Shard 9 — Conformance harness reuse + e2e xfail.** Reuse the vendored
  `canonical.json` via the `VendoredConformanceLoader` pattern; ABC-composition
  harness runs now; per-vector outcome + e2e `execute()` are strict-xfail pending
  #1182. _Value-anchor:_ brief acceptance "conformance harness reuses the shared
  canonical set". Invariants: 3 (fixture loads/validates, ABC composes, per-vector
  strict-xfail mirrors email).

Sharding note: shards 2–6 are the load-bearing core; 1, 7, 8 are boilerplate-or-
infra (run larger safely). Shard 5 is the only one at the upper invariant budget —
keep it single-session with the Tier-1 loop live. Do NOT merge 5+6 (would exceed
the invariant budget: connector primitives + full composition = >10 invariants).

## Brief corrections (the GATE before /todos)

1. **Inbound transport default flips from Socket Mode to a bounded `conversations.history`
   pull.** The brief's v0 lean ("Socket Mode unless /analyze identifies a structural
   issue") — `/analyze` identified the structural issue: a persistent socket
   conflicts with the one-shot `read` thunk (ADR-S1). The acceptance criterion
   "inbound message read via Socket Mode (or Events API, per /analyze)" is satisfied
   by the bounded Web API history pull, which is the transport that fits the `read`
   primitive. Socket Mode is re-scoped to a future dispatch-layer event consumer.
2. **`runtime.execute()` is ASYNC** (re-verified against the wheel) — the email
   cluster docs' "synchronous" claim is superseded by `specs/runtime-composition.md`
   (PR #5). The connector wires `await runtime.execute(...)`.
3. **`slack-mock` (the brief's named Tier-2 candidate) is stale/unmaintained;**
   Tier-2 uses a current-Web-API single-container stub instead (ADR-S4), preserving
   the brief's intent (single reproducible container, no boundary mocking).
4. **#1035 "real PACT + real Postgres"** remains aspirational vs the shipped
   in-memory audit (inherited from email BLOCKER-2). The buildable path is the
   shipped API.

## Out of scope (v0) — bounding, not gaps

Socket Mode / Events API real-time consumption; OAuth multi-workspace install;
Slack Connect / Enterprise Grid; interactive surfaces (slash commands, modals);
file uploads; rich Block Kit composition; cursor-paginated deep history backfill;
LLM-routed responses (dispatch/kaizen layer). Each is a later shard or a different
layer — NONE is a hole inside v0's perimeter.
