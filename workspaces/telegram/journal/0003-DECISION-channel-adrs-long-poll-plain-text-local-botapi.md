---
type: DECISION
date: 2026-05-27
created_at: 2026-05-27T00:10:00Z
author: agent
session_id: telegram-connector-analyze
session_turn: 5
project: telegram-connector
topic: Channel ADRs T1-T5 — long-poll inbound, plain-text outbound default, dual-key resolver, local Bot API real-infra, caller-owned retry
phase: analyze
tags: [decision, adr, transport, identity, test-infra, telegram]
---

# DECISION — Telegram channel ADRs (T1–T5)

## Context

Telegram is the second pattern-lift after email; shared SDK ADRs 1–5 are
inherited. Five channel-specific deltas (the brief's open questions 1–5) needed
resolution against the shipped API and the inherited audited-thunk contract.

## Decisions

- **ADR-T1 — inbound = long-polling (`getUpdates`).** A single bounded HTTP
  request-response maps 1:1 onto the one-shot audited read thunk. Webhook
  (`setWebhook`) needs an inbound HTTPS server (framework-first-BLOCKED as
  hand-rolled server code) + a queue/drain restructure that breaks the clean
  one-shot mapping. Webhook is v0 out-of-scope.
  Alternatives: webhook (rejected — server + queue), hybrid (rejected — two
  components for v0).
- **ADR-T2 — outbound = `sendMessage`; v0 `parse_mode` default = plain text.**
  Plain carries no escaping ambiguity and no formatting-injection surface.
  Validation at the message-construction boundary (control-char reject, text ≤
  4096 UTF-16 units, `chat_id` shape) covers every send route. HTML/MarkdownV2
  escaping out-of-scope (MarkdownV2's 18 reserved chars are error-prone — defer).
- **ADR-T3 — resolver dual-keyed by `user_id` + `chat_id`; `authenticate` resolves
  by `delegate_id`.** `@username` is never a key (ref-unsafe + mutable;
  journal/0001). Unknown → fail-closed `Reject`.
- **ADR-T4 — Tier 2/3 real-infra = local Bot API HTTP service** (hermetic
  surrogate implementing `sendMessage` + `getUpdates`, real socket + JSON cycle).
  Live-bot path (Option A) is an optional secret-gated extra, skipped by default.
  MTProto test server (Option C) rejected — wrong protocol layer (user-account,
  not Bot API).
- **ADR-T5 — rate-limit `429`/`retry_after` surfaced as typed error; retry/backoff
  deferred to caller.** Retry-under-audit would re-run the audited thunk and emit
  multiple `SignedActionEnvelope`s for one logical send (audit-chain ambiguity).
  Documented v0 boundary, not a stub.

## Consequences

The connector is a transport substitution of the email shape: `httpx`-backed
`sendMessage`/`getUpdates` replace SMTP/IMAP; the dual-key resolver, signing
helpers, in-memory ledger/revocation adapters, and runtime composition are
inherited. No NEW blocker beyond the two inherited from email (#1182, #1035). 7
shards planned (`02-plans/01-architecture.md`), each within the per-session
capacity budget.

## For Discussion

1. Every ADR (T1–T5) refines an inherited shared ADR for the HTTP transport. Is
   any decision here one the email pattern did NOT already shape, or is Telegram a
   pure transport-substitution confirmation of the pattern's generality?
2. ADR-T5 defers retry to the caller to keep one logical send = one audited
   envelope. Had retry lived in the transport, the audit chain would carry N
   envelopes per send. Which is the lesser evil for a v0 whose point is verifiable
   single-action attestation?
3. ADR-T4's local Bot API service is a real socket but deterministic state. If the
   OSS surrogate proves heavier than a 2-method HTTP stub, does dropping to a
   minimal hand-rolled deterministic service still count as "real infra," or does
   it cross into the Tier-2/3 mock territory that `specs/test-infrastructure.md`
   blocks?
