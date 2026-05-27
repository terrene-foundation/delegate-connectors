# Spec — Slack Connector (v0)

> **Status: design spec (v0) — not yet implemented.** Per `rules/spec-accuracy.md`
> Rule 5, a spec for unshipped behavior lives in `02-plans/`, not `specs/`. This
> promotes to `specs/slack-connector.md` (and a `specs/_index.md` row) when
> `/implement` lands the connector code on `main`. Until then it is the v0
> implementation contract.

Implements `Connector` (see `connector-contract.md`) for
Slack. Same ABC + audit-receipt shape as the email connector; different transport.

## Responsibilities (mapped to the ABC)

| ABC member                               | Slack behavior                                                                                                                                                                                  |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate(identity, envelope)`       | Resolve the dispatch identity's `delegate_id` to a `Principal` against a `SlackPrincipalResolver`. Unknown identity → disposition per § Unknown-sender below.                                   |
| `write(action, *, identity, envelope)`   | `action` is a thunk wrapping a Slack Web API **`chat.postMessage`**. Execute under audit; return `SignedActionEnvelope`. The post is the auditable external side-effect.                        |
| `read(query, *, identity, envelope)`     | `query` is a thunk wrapping a Slack Web API **`conversations.history` fetch** (bounded page of channel messages). Execute under audit; return `(messages, AttestedReadReceipt)`.                |
| `invoke(payload, *, identity, envelope)` | Single-method entry: authenticate (fail-closed) FIRST, then dispatch to post (write); return `ConnectorInvocationResult(payload, audit_events, tenant_id_observed, external_side_effect=True)`. |
| `auth_verifier`                          | `Ed25519Verifier(directory)` (shipped concrete).                                                                                                                                                |
| `ledger`                                 | `InMemoryKnowledgeLedger` — a Protocol-satisfying deterministic adapter (the SDK ships the `KnowledgeLedger` Protocol, no concrete). Never carries credentials.                                 |
| `revocation`                             | `NeverRevokedChannel` — a Protocol-satisfying deterministic adapter (`is_revoked` returns `False`; v0 has no revocation source).                                                                |

## Transport

- **`chat.postMessage`** (outbound): the Slack Web API method, via the
  `slack_sdk` async client (`AsyncWebClient`). Bot token from `.env`
  (`SLACK_BOT_TOKEN`) — never hardcoded (`security.md`). `SLACK_API_BASE_URL`
  overrides the base URL for the Tier-2 mock-server container.
- **`conversations.history`** (inbound): the bounded-pull Web API method via the
  same `AsyncWebClient` and the same `SLACK_BOT_TOKEN`. One bot-token credential
  family covers both directions. Socket Mode is NOT used (a persistent socket
  conflicts with the one-shot `read` thunk — see `workspaces/slack/01-analysis/01-inbound-transport.md`).

## Principal resolution

v0: exact-match lookup of the dispatch identity's `delegate_id` against
`SlackPrincipalResolver` (dual-keyed — also indexed by the literal Slack id for
payload attribution; `delegate_id` is the primary resolution key). Slack ids
(`U…`/`C…`) are validated for shape and case-significant (not lowercased).
Multi-workspace / team-scoped resolution is deferred — out of v0 scope.

## Unknown-sender disposition

`expected` outcomes are the closed enum `{Accept, Reject, EscalateToHuman}`
(conformance). An unknown identity MUST resolve to **`Reject`** in v0 (fail-closed;
not `Accept`). The `Reject` is enforced on the `invoke` hot path (authenticate runs
before any `chat.postMessage`). `EscalateToHuman` reserved for a later policy shard.

## v0 out-of-scope

Socket Mode / Events API real-time consumption; OAuth multi-workspace install;
Slack Connect / Enterprise Grid; interactive surfaces (slash commands, shortcuts,
modals); file uploads; rich Block Kit composition beyond a baseline text message;
cursor-paginated deep history backfill; dispatch / classification / supervisor
(spine concerns); the other 2 connectors.

## Security

- All credentials via `.env`; root `.env` git-ignored; `.env.example` template only.
- No secrets in logs or audit payloads (the audited read manifest carries message
  `ts` ids + count only, never message body bytes).
- Input validation at the `OutboundSlackMessage` construction boundary: the
  `channel` (and any id-bound field) is shape-validated, and user-controlled `text`
  is mrkdwn-escaped (`&`/`<`/`>`), so an injected `<@U…>` mention / `<!channel>`
  broadcast / `<url|label>` link cannot render live. Every send route builds an
  `OutboundSlackMessage` first, so the boundary covers them all.
