<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# Spec — delegate-connector-slack

**Status**: SHIPPED (v0 merged to main)
**Package**: `connectors/slack/` → `delegate_connectors.slack`
**Implements**: the shipped `kailash.delegate.Connector` ABC (kailash 2.26.2)

---

## 1. Purpose

`delegate-connector-slack` is an OSS Python connector for the Terrene Delegate
substrate (`kailash.delegate`). It binds Slack (`chat.postMessage` outbound +
`conversations.history` inbound) to the shipped `Connector` ABC, producing real
signed receipts that verify under a real `Ed25519Verifier`. It is the same
contract the email + WhatsApp connectors implement, with a Slack Web API
transport. Pure Python — no Rust-sibling dependency.

It subclasses `Connector` **directly** (ADR-1), NOT `LegacyInvokeConnector`
(whose proxied `read`/`write` emit empty, unverifiable receipts). Every receipt
this connector produces is NON-EMPTY and verifies under a real
`Ed25519Verifier`.

## 2. The 4 ABC members

| Member         | Slack binding                                                         |
| -------------- | --------------------------------------------------------------------- |
| `write`        | `chat.postMessage` outbound, under audit → `SignedActionEnvelope`     |
| `read`         | bounded `conversations.history` pull, under audit → `(msgs, receipt)` |
| `authenticate` | `delegate_id` → `Principal`; unknown → fail-closed `Reject`           |
| `invoke`       | authenticate-first → `chat.postMessage` via the audited write path    |

`write` signs over the FULL receipt identity (`{payload, signer_delegate_id,
action_id, observed_at}`), so two identical-payload posts produce distinct signed
bytes. `read`'s audited manifest carries the channel + message `ts` ids + count
ONLY — never message body bytes. `invoke` authenticates FIRST: an unknown sender
raises `ConnectorAuthenticationError` (fail-closed `Reject`) before any
`OutboundSlackMessage` is constructed and before any `chat.postMessage` fires.

## 3. Trust properties (3)

| Property        | v0 binding                                                 |
| --------------- | ---------------------------------------------------------- |
| `auth_verifier` | the supplied real `Ed25519Verifier`                        |
| `ledger`        | `InMemoryKnowledgeLedger` (Protocol-satisfying, in-memory) |
| `revocation`    | `NeverRevokedChannel` (Protocol-satisfying, never-revoked) |

The trust-property concretes are Protocol-satisfying deterministic data
endpoints, NOT custom trust primitives (the SDK ships the Protocols, not
concretes). Signing / verification stays with the shipped Ed25519 stack. No
credential ever enters a log line or an audit payload.

## 4. Inbound transport — bounded pull, not Socket Mode (ADR-S1)

Inbound is a bounded `conversations.history` pull (one page per `read` call,
`limit` defaulting to Slack's documented per-page cap of 100), NOT Socket Mode. A
persistent Socket Mode connection conflicts with the connector's one-shot `read`
thunk contract (one bounded fetch per audited read receipt). v0 does not
cursor-paginate; one page per call matches the single-audit-receipt-per-read
contract.

## 5. Injection / validation boundary (ADR-S3)

`OutboundSlackMessage.__post_init__` is the single injection-validation boundary:

- `channel` is shape-validated via `normalize_slack_id` — a malformed channel id
  raises `SlackFieldError` before any Slack API call.
- `text` is mrkdwn-escaped (`&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`, `&`
  first), so an injected `<@U…>` mention / `<!channel>` broadcast /
  `<url|label>` link becomes inert text.

Slack ids are CASE-SIGNIFICANT — `normalize_slack_id` trims + shape-validates but
does NOT lowercase (a deliberate divergence from email's `normalize_address`).
Block Kit / `attachments` / `blocks` are OUT of v0 scope; scoping them out
removes the structural-injection vector entirely.

## 6. Identity resolution (ADR-S2)

`SlackPrincipalResolver` is dual-keyed: `delegate_id` is the PRIMARY resolution
key (drives `authenticate`, for cross-connector uniformity and stability across
handle/workspace changes); the Slack id is a SECONDARY literal index for payload
attribution. Resolution is exact-match in v0. Unknown identity → fail-closed
`Reject` (never `Accept`); `EscalateToHuman` is reserved for a later policy
shard. The closed disposition enum (`UnknownSenderDisposition`) mirrors the
conformance `BehaviouralOutcome` enum `{Accept, Reject, EscalateToHuman}`.

## 7. Runtime composition

`build_slack_runtime(transport=..., sender_slack_id=...)` composes the full
shipped runtime — `PrincipalDirectory` + `Ed25519Verifier`, in-memory
`AuditChainEngine` over a `TrustLineageChain`, `TenantScopedCascade` (root
grantee registered with a real Ed25519 grant proof), `Role`, `DispatchSurface`,
and `DelegateRuntime` — using spine-shipped concretes for everything except the
connector. No mocks; no Postgres; no PACT (the shipped runtime audit is
in-memory).

## 8. Test topology

| Tier        | Backing                                                              |
| ----------- | -------------------------------------------------------------------- |
| Tier-1 unit | pure-Python, no I/O (transport seam stubbed at the SDK boundary)     |
| Tier-2/3    | in-process protocol-faithful Slack Web API server over a real socket |
| Conformance | monorepo-shared canonical vector set; per-vector outcome xfail-gated |
| Regression  | behavioral security guards (NEVER deleted)                           |

Because `slack_sdk`'s `AsyncWebClient` is aiohttp-based (so `httpx.MockTransport`
cannot intercept it), the Tier-2 surrogate is a real in-process aiohttp server
bound to an ephemeral port (ADR-S4) — the connector's real `AsyncWebClient` is
pointed at it via `SLACK_API_BASE_URL`. This is a Protocol-satisfying
deterministic adapter over a real socket, not a mock at the connector boundary,
so the integration tests RUN in CI. The opt-in Tier-3 live-Slack test skips with
a clear "cannot execute" reason unless `SLACK_LIVE_E2E=1` plus real
`SLACK_BOT_TOKEN` + `SLACK_LIVE_E2E_CHANNEL` are set; it never falls back to a
mock.

The deterministic Tier-2 `ts` (a content hash of `channel + text`) makes two
identical posts produce byte-identical signed envelopes — the
receipt-determinism invariant holds at the transport boundary, exercised by
`assert_receipts_agree` across two deterministic runs.

## 9. Known SDK blocker

`runtime.execute()` is gated on kailash-py#1182: the shipped `kailash.delegate`
runtime audit-emit path signs the event payload bytes while
`AuditChainEngine.emit_event` verifies the signature against the full
audit-entry signing bytes, so `execute()` fails at the first phase transition
under any real verifier. This is an SDK bug, not a connector bug — the
connector's own `read`/`write` receipts verify correctly. The end-to-end
`execute()` outcome assertion is a strict xfail in the conformance + e2e suites;
the connector-level post → history round-trip and receipt verification are not
gated. Same failure mode as the email + WhatsApp connectors.

## 10. Configuration

All credentials are env-only (no silent default; a typed `SlackWebConfigError`
on absence):

- `SLACK_BOT_TOKEN` (required) — the `xoxb-…` bot token; one credential family
  covers both directions.
- `SLACK_API_BASE_URL` (optional) — overrides the default Slack Web API base URL
  so the in-process test server can stand in at the same seam the live transport
  uses.

Nothing is hardcoded; nothing is logged.

## 11. Cross-references

- `specs/connector-contract.md` — the shared ABC contract
- `specs/conformance.md` — the conformance harness + the #1182 gate
- `specs/test-infrastructure.md` — the 4-tier topology
- `connectors/slack/README.md` — the shipped-contract overview
- `workspaces/slack/01-analysis/00-synthesis.md` — the ADR-S1..S4 derivation
- `workspaces/slack/02-plans/02-connector-spec.md` — the source plan promoted here
