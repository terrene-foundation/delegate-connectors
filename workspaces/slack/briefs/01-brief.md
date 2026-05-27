# Brief — Slack Connector (v0)

> **Provenance:** Agent-drafted 2026-05-27 under `/autonomize` after the email
> connector v0 shipped + `/redteam` re-validation CONVERGED. The user-stated
> directive was "all 3 for F3 in parallel" (slack/telegram/whatsapp), so this
> brief opens the slack track. Pattern lift from `workspaces/email/briefs/01-brief.md`.
> **User amendment expected** — flag anything mis-scoped.

## Goal

Ship the second OSS Python connector in this monorepo: a **Slack connector**
that implements the `kailash.delegate.Connector` contract (the same ABC the
email connector satisfies) and re-uses the spine-shipped trust + audit
concretes. v0 demonstrates the connector pattern generalizes beyond email —
same ABC, same audit-receipt shape, different transport.

## What's known (cross-channel invariants — reuse from email v0)

The connector ABC + composition shape is shared across channels:

- Base class is the shipped `Connector` ABC directly (ADR-1 from email v0).
  `LegacyInvokeConnector` is REJECTED for the same reason (empty receipts).
- Required members: 4 methods + 3 properties (`authenticate` / `invoke` /
  `read` / `write` + `auth_verifier` / `ledger` / `revocation`).
- Trust + audit: spine-shipped `Ed25519Verifier`, `PrincipalDirectory`,
  `AuditChainEngine` over `TrustLineageChain`, `TenantScopedCascade`.
- Receipts: `SignedActionEnvelope` (write), `AttestedReadReceipt` (read);
  bind FULL identity into signing bytes (signer + action_id + observed_at),
  not bare payload (the email v0 receipt-binding fix applies identically).
- `runtime.execute()` is async (per the corrected `specs/runtime-composition.md`).
  The same kailash-py#1182 SDK bug gates the end-to-end e2e (xfail-strict).
- Credentials env-only (`SLACK_*`); no hardcoded secrets; nothing logged.

## v0 Scope — channel-specific shape

**In scope:**

1. A `SlackConnector` implementing the shipped `Connector` contract directly.
2. **Outbound** — post a message to a Slack channel as the `write`/`invoke`
   action. Transport: Slack Web API `chat.postMessage`.
3. **Inbound** — read messages from a channel as the `read` path. Transport
   choice deferred to `/analyze`: **Socket Mode** (websocket, easier dev / no
   public endpoint required) vs **Events API** (webhook, prod-shaped but
   requires inbound HTTP). For v0 default lean: Socket Mode unless `/analyze`
   identifies a structural issue with thunk-wrapping a long-lived socket.
4. `authenticate()` resolves a Slack identity (user id or channel id) to a
   `Principal` against a `PrincipalDirectory`. Unknown identity →
   fail-closed `Reject` (closed enum, matches email v0).
5. Header-injection defenses applied at the message-construction boundary
   (Slack's `text` / `attachments` carry their own injection surface — Block
   Kit JSON; subject-to-research at `/analyze`).
6. Tier-1 unit + Tier-2/3 integration tests against a real Slack workspace
   OR a Slack-API mock server (no commercial in-house dependency). Container
   options for `/analyze`: `slack-mock` (open source) or live workspace
   under a test bot token.

**Out of scope (v0 — do not chase):**

- Slack Connect / Enterprise Grid / multi-workspace shared channels.
- Interactive surfaces (slash commands, shortcuts, modals).
- File uploads, snippet rendering, rich Block Kit composition beyond a
  baseline text message.
- Calling LLM-routed responses inside the connector (that is the
  dispatch/kaizen layer, not the connector).
- The other two connectors (telegram, whatsapp).

## Acceptance criteria

- [ ] `SlackConnector` satisfies `kailash.delegate.Connector` ABC — every
      abstract member implemented (ABC instantiation succeeds).
- [ ] Outbound message post via Slack Web API verified to arrive at the
      destination channel (real-infra check, not a mocked client).
- [ ] Inbound message read via Socket Mode (or Events API, per `/analyze`)
      returns a signed `AttestedReadReceipt` that verifies under the shipped
      `Ed25519Verifier`.
- [ ] `authenticate()` resolves a known Slack identity to a `Principal`;
      unknown → `ConnectorAuthenticationError` (fail-closed Reject) BEFORE
      any Slack API call fires on the `invoke` hot path.
- [ ] Receipts bind FULL identity (signer + action_id + observed_at);
      tamper of any field fails verification.
- [ ] All credentials read from `.env`; `.env` git-ignored; no credential in
      any log line or audit payload.
- [ ] Tier-1 unit suite + Tier-2/3 real-infra suite both green; conformance
      harness reuses the monorepo-shared canonical set (
      `tests/fixtures/delegate-conformance/canonical.json`).
- [ ] Apache-2.0 SPDX header on every source file; no dependency on the
      proprietary Rust sibling; package shape matches `specs/monorepo-layout.md`
      (`connectors/slack/`, namespace `delegate_connectors.slack`).

## Open questions for /analyze

1. **Inbound transport** — Socket Mode (websocket, persistent connection,
   easier dev) vs Events API (webhook, prod-shaped, requires inbound HTTP).
   Which fits the `read(query, ...)` thunk shape better? Does a persistent
   socket conflict with the audit thunk's one-shot semantics?
2. **Identity model** — Slack identifies users by workspace-scoped user ids
   (`U…`), channels by ids (`C…`). The directory's resolution key needs to
   pin a clear primary (user id? user id + workspace id pair?). Mirror the
   email connector's dual-keyed pattern (delegate_id + literal email)?
3. **Outbound injection surface** — Block Kit JSON in `attachments` carries
   its own injection surface (JSON escaping, mrkdwn vs plain). Where is the
   validation boundary?
4. **Test-infra topology** — is there an open-source Slack-API mock server
   suitable for Tier-2/3 (analogous to Mailpit/GreenMail for email), or does
   the integration tier need a live workspace + a test bot token?
5. **OAuth installation flow** — for v0, assume a single pre-installed bot
   token in `.env`. Multi-workspace OAuth is out of v0 scope but the
   directory + tenant cascade design should not BLOCK it later.
6. **#1035 alignment** — does the issue's connector-set wording (#1035) pin
   any slack-specific contract surface beyond what the email v0 delivered?
