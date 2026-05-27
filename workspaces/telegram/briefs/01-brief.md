# Brief — Telegram Connector (v0)

> **Provenance:** Agent-drafted 2026-05-27 under `/autonomize` after the email
> connector v0 shipped + `/redteam` re-validation CONVERGED. The user-stated
> directive was "all 3 for F3 in parallel" (slack/telegram/whatsapp), so this
> brief opens the telegram track. Pattern lift from `workspaces/email/briefs/01-brief.md`.
> **User amendment expected** — flag anything mis-scoped.

## Goal

Ship the third OSS Python connector in this monorepo: a **Telegram connector**
that implements the `kailash.delegate.Connector` contract (the same ABC the
email connector satisfies). v0 is the second pattern lift after email — same
ABC, same audit-receipt shape, different transport. Telegram is the simplest
of the three F3 channels (single-token auth, HTTP-only Bot API), so it likely
moves fastest and validates that the pattern generalizes beyond email's IMAP/SMTP.

## What's known (cross-channel invariants — reuse from email v0)

Identical to the slack brief — repeated here so each workspace is self-contained:

- Base class is the shipped `Connector` ABC directly (ADR-1 from email v0).
- Required members: 4 methods + 3 properties (`authenticate` / `invoke` /
  `read` / `write` + `auth_verifier` / `ledger` / `revocation`).
- Trust + audit: spine-shipped `Ed25519Verifier`, `PrincipalDirectory`,
  `AuditChainEngine` over `TrustLineageChain`, `TenantScopedCascade`.
- Receipts: `SignedActionEnvelope` (write), `AttestedReadReceipt` (read);
  bind FULL identity into signing bytes (signer + action_id + observed_at).
- `runtime.execute()` is async; kailash-py#1182 gates the e2e (xfail-strict).
- Credentials env-only (`TELEGRAM_*`); no hardcoded secrets; nothing logged.

## v0 Scope — channel-specific shape

**In scope:**

1. A `TelegramConnector` implementing the shipped `Connector` contract directly.
2. **Outbound** — send a Telegram message as the `write`/`invoke` action.
   Transport: Telegram Bot API HTTP endpoint `sendMessage`.
3. **Inbound** — read messages as the `read` path. Telegram offers two
   inbound modes: **long-polling** (`getUpdates`, simple, no public endpoint)
   vs **webhook** (`setWebhook`, prod-shaped, requires inbound HTTP). For v0
   default lean: long-polling unless `/analyze` finds it incompatible with
   the read-thunk's one-shot semantics.
4. `authenticate()` resolves a Telegram user id (or chat id) to a `Principal`
   against a `PrincipalDirectory`. Unknown identity → fail-closed `Reject`.
5. Text-content sanitization at the message-construction boundary (Telegram
   supports HTML / MarkdownV2 / plain — each has its own escaping surface).
6. Tier-1 unit + Tier-2/3 integration tests against a real-infra Telegram
   surrogate (no commercial in-house dependency). The most plausible
   real-infra option is a local **MTProto test server** OR a live test bot
   talking to a sandbox chat — `/analyze` decides.

**Out of scope (v0 — do not chase):**

- Channels, supergroups, topics (forum threads), inline queries, callback
  buttons, inline keyboards beyond a baseline text exchange.
- File / media uploads (photo, document, sticker, voice, video).
- Telegram MTProto-API (user-account) integration — Bot API only for v0.
- Payments, Web Apps, mini-apps, Game API.
- LLM-routed responses inside the connector (dispatch/kaizen concern).
- The other two connectors (slack, whatsapp).

## Acceptance criteria

- [ ] `TelegramConnector` satisfies `kailash.delegate.Connector` ABC — every
      abstract member implemented (ABC instantiation succeeds).
- [ ] Outbound message send via Bot API `sendMessage` verified to arrive at
      the destination chat (real-infra check, not a mocked client).
- [ ] Inbound message read via long-polling (or webhook per `/analyze`)
      returns a signed `AttestedReadReceipt` that verifies under the shipped
      `Ed25519Verifier`.
- [ ] `authenticate()` resolves a known Telegram identity to a `Principal`;
      unknown → `ConnectorAuthenticationError` (fail-closed Reject) BEFORE
      any Bot API call fires on the `invoke` hot path.
- [ ] Receipts bind FULL identity (signer + action_id + observed_at);
      tamper of any field fails verification.
- [ ] All credentials read from `.env`; `.env` git-ignored; no credential in
      any log line or audit payload.
- [ ] Tier-1 unit suite + Tier-2/3 real-infra suite both green; conformance
      harness reuses the monorepo-shared canonical set.
- [ ] Apache-2.0 SPDX header on every source file; no dependency on the
      proprietary Rust sibling; package shape matches `specs/monorepo-layout.md`
      (`connectors/telegram/`, namespace `delegate_connectors.telegram`).

## Open questions for /analyze

1. **Inbound transport** — long-polling (`getUpdates` loop, simple, no
   public endpoint) vs webhook (`setWebhook`, requires inbound HTTP). The
   read-thunk's one-shot semantics fit long-polling cleanly; does webhook
   require restructuring (e.g. a queue + per-fetch drain)?
2. **Identity model** — Telegram identifies users by integer `user_id` and
   chats by `chat_id`. Bots only see `user_id` for direct senders, and
   `chat_id` for groups. The directory's primary key: `user_id`? `chat_id`?
   Tuple? Mirror email's dual-keyed pattern?
3. **Outbound formatting surface** — `parse_mode` ∈ {HTML, MarkdownV2, plain}.
   Each has distinct escaping requirements (MarkdownV2 is famously
   error-prone). Where is the validation boundary, and what is the v0 default?
4. **Test-infra topology** — options:
   - Local Telegram-test-server (open source, MTProto-compatible)?
   - Mocked Bot API endpoint (HTTP-only, simpler) — does an open-source
     mock exist?
   - Live test bot + sandbox chat — credentials in CI?
5. **Rate limits** — Telegram Bot API has per-second + per-minute limits.
   Should the transport encode retry/backoff at v0, or defer to the caller?
6. **#1035 alignment** — does the issue pin any telegram-specific contract
   surface beyond what email v0 delivered?
