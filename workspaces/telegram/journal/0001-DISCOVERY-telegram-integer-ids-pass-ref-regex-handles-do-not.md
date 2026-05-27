---
type: DISCOVERY
date: 2026-05-27
created_at: 2026-05-27T00:00:00Z
author: agent
session_id: telegram-connector-analyze
session_turn: 4
project: telegram-connector
topic: Telegram integer user_id/chat_id (stringified) pass the DelegateIdentity ref regex; @username handles are rejected
phase: analyze
tags: [sdk-constraint, identity, principal-resolution, telegram, grounding]
---

# DISCOVERY — Telegram integer ids pass the DelegateIdentity ref regex; @handles do not

## Finding (kailash 2.26.2, introspected via the repo-local interpreter)

The email connector found that `DelegateIdentity` ref fields are validated against
`^[a-zA-Z0-9_-]+$`, so an email address (`@`, `.`) is rejected at construction
(`workspaces/email/journal/0006-DISCOVERY-*`). I re-introspected the wheel with
Telegram-shaped values:

```
DelegateIdentity(delegate_id=uuid4(), sovereign_ref="123456789",
    role_binding_ref="tg-chat-987654321", genesis_ref="tg-genesis",
    principal_kind="delegate")
→ ACCEPTED   sovereign_ref="123456789"  role_binding_ref="tg-chat-987654321"

DelegateIdentity(..., sovereign_ref="@alice", ...)
→ REJECTED   ValueError: contains unsafe characters (must match ^[a-zA-Z0-9_-]+$)
```

- Telegram's integer `user_id` / `chat_id`, stringified, PASS the regex (digits +
  `-` are allowed). The channel's native identifiers are already ref-safe — no
  transformation needed, unlike email's address.
- Telegram `@username` handles are REJECTED (`@` is unsafe) — the same failure
  mode as an email address, AND handles are mutable, so a handle is never a stable
  key.

## Consequence

The dual-keyed resolver (ADR-T3) keys by stringified integer `user_id` + `chat_id`
(both ref-safe — they can even ride on `DelegateIdentity` ref fields, which
email's address could not) plus the `delegate_id` view `authenticate` uses. A
`@handle` is never a resolution key; a supplied handle resolves to fail-closed
`Reject`. This strengthens (does not break) the email dual-key pattern.

## For Discussion

1. Telegram's integer ids CAN ride on the ref fields (`sovereign_ref` = `user_id`,
   `role_binding_ref` = `chat_id`) where email's address could not. Does using the
   ref fields add resolution robustness, or create two paths that can drift?
2. If the Bot API had keyed identity on `@username` instead of integers, would the
   resolution model have inherited email's address-mutability fragility
   (journal/0006 §2) wholesale?
3. The conformance `BehaviouralOutcome` is outcome-keyed, not key-keyed. Does
   resolving by `delegate_id` vs `user_id` vs `chat_id` change any vector's
   `expected`, or is the keying invisible to the behavioural contract?
