---
type: DISCOVERY
date: 2026-05-27
author: agent
project: slack-connector
topic: A persistent Socket Mode websocket structurally conflicts with the one-shot read-thunk; v0 read is a bounded conversations.history pull
phase: analyze
tags: [transport, read-thunk, socket-mode, adr-s1]
---

# DISCOVERY — Socket Mode conflicts with the one-shot `read` thunk

## Finding

The shipped `Connector.read(query, *, identity, envelope)` takes a zero-arg async
thunk, awaits it ONCE, and returns one bounded value + one `AttestedReadReceipt`
(verified against kailash 2.26.2; reference impl
`connectors/email/.../connector.py::read` does exactly one `await query()`).

A Slack Socket Mode connection is a persistent WebSocket that PUSHES events
indefinitely. It conflicts with the `read` thunk on three structural axes:

1. **No bounded return** — the socket never "completes a fetch"; it streams events
   forever, so the thunk could only attest one arbitrary pushed event, not a defined
   query result.
2. **Lifecycle ownership** — a persistent socket carries a connect/reconnect/
   heartbeat daemon the stateless connector `read` seam must not own (that is a
   dispatch-layer concern, out of v0 scope).
3. **Receipt cardinality** — one `read` = one canonical manifest = one receipt; an
   open event stream has no single manifest to attest.

## Resolution (ADR-S1)

v0 `read` is a **bounded `conversations.history(channel, limit)` pull** wrapped in
the thunk — the structural twin of email's IMAP `fetch(criteria)`. Socket Mode is
re-scoped to a future dispatch-layer event consumer (NOT the connector primitive).
One bot-token credential family (`SLACK_BOT_TOKEN`) covers both `read` (history)
and `write` (`chat.postMessage`).

The brief's v0 lean ("Socket Mode unless /analyze identifies a structural issue")
explicitly anticipated this — the escape clause fired. Recorded as brief-correction
#1 in `02-plans/01-architecture.md`.
