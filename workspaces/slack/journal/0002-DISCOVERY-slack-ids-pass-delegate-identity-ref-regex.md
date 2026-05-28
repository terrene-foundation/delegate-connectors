---
type: DISCOVERY
date: 2026-05-27
author: agent
project: slack-connector
topic: Slack ids pass the DelegateIdentity ref regex (unlike email addresses) — a clean delta — but the dispatch resolution key stays delegate_id for uniformity
phase: analyze
tags: [identity, principal-resolution, adr-s2]
---

# DISCOVERY — Slack ids pass the `DelegateIdentity` ref regex

## Finding (kailash 2.26.2, introspected this session)

The shipped `DelegateIdentity` validates `sovereign_ref` / `role_binding_ref` /
`genesis_ref` against `^[a-zA-Z0-9_-]+$`. Email hit this: `@`/`.` addresses are
REJECTED, so email resolves by `delegate_id` and puts the literal email on the
payload (`workspaces/email/journal/0006`).

Slack ids are alphanumeric-safe and PASS the same regex — verified:

| literal              | regex | `DelegateIdentity` ref |
| -------------------- | ----- | ---------------------- |
| `U07ABCDE123` (user) | pass  | ACCEPTED               |
| `C0123456789` (chan) | pass  | ACCEPTED               |
| `alice@example.com`  | fail  | REJECTED (email)       |

So Slack COULD carry the user id on a ref field — a cleaner story than email.

## Resolution (ADR-S2)

Despite the difference, the dispatch resolution key stays **`delegate_id`**
(primary), with the Slack id as a secondary literal index, mirroring email's
dual-keyed `EmailPrincipalResolver`. Rationale: (a) cross-connector uniformity —
`SlackConnector.authenticate` stays byte-identical in shape to email's, which is
the brief's whole thesis; (b) `delegate_id` is stable across handle/workspace
changes. The team/workspace id lives in `Principal.claims` for forward-compat with
multi-workspace OAuth (a later shard) without entering the v0 lookup key.

`normalize_slack_id` is shape-validate + trim only — NOT lowercase (Slack ids are
case-significant, a divergence from email's `normalize_address`).
