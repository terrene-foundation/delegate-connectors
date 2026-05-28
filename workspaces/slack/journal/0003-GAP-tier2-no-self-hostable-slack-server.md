---
type: GAP
date: 2026-05-27
author: agent
project: slack-connector
topic: Slack has no self-hostable real server; the brief's named slack-mock is stale; Tier-2 needs a current-Web-API single-container stub, decided in ADR-S4
phase: analyze
tags: [test-infra, tier2, slack-mock, adr-s4]
---

# GAP — No self-hostable real Slack server; `slack-mock` is stale

## Gap

Email's Tier-2/3 uses real mail containers (Mailpit + GreenMail) — a self-hostable
real boundary. Slack is a hosted SaaS with NO self-hostable server, so the email
real-infra model cannot be copied literally.

The brief names `slack-mock` (open source) as the Tier-2 candidate. Survey: the
original Node `slack-mock` is stale (no recent release; targets the legacy RTM/old
Web API) — disqualified per `rules/dependencies.md` (no unmaintained deps).

## Disposition (ADR-S4 — not blocking)

Tier-2 uses a **single Web API mock-server container** serving the two methods v0
uses (`chat.postMessage` record+return-`ts`, `conversations.history` replay),
talked to by a real `AsyncWebClient(base_url=...)` — NO mocking at the connector
boundary (the _server_ is the local stub, exactly as Mailpit is a local SMTP
server). It is the CI-runnable Mailpit analogue: single reproducible container, no
per-job manual setup. The container is WireMock/Prism-seeded with the two response
shapes OR a small purpose-built stub.

Tier-3 (opt-in, NOT default CI) = live workspace + test bot token behind a
`requires_live_slack` skip-gate (mirrors email's `requires_greenmail`).
Live-workspace-as-Tier-2 is rejected — it fails the CI-runnable-without-manual-setup
bar (provisioned workspace + per-job secret + rate-limit flakiness).

This is a topology decision, NOT a convergence blocker. The only inherited
convergence gate is kailash-py#1182 (e2e `execute()`), tracked at
`specs/conformance.md` and `workspaces/email/journal/0005`.
