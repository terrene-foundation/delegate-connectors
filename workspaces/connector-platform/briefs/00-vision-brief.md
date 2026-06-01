# Vision Brief — Trust-Native Connector Marketplace

**Date:** 2026-06-01
**Source:** user directive, this session.

## The vision (user's words)

> "given that we may end up with thousands of plugins created by contributors, its not
> possible to maintain packages for each of them. we need an easy way to write plugins.
> … I see this as the n8n killer."

## What the user is asking for

1. **Scale to thousands of contributor-authored connectors** — the core team cannot maintain
   a package per connector. Contributors must own and publish their own.
2. **An easy way to write a plugin** — low barrier to authoring a connector, especially for
   the common case (HTTP/REST APIs).
3. **Beat n8n** — be the better connector/automation platform.

## The wedge

n8n (and Zapier / Make / Airbyte) cannot safely run untrusted community connectors: n8n hands
each community node your **decrypted** credentials via `getCredentials()` and runs it
**in-process at full host privilege** (the exact vector of the Jan-2026 n8n supply-chain
campaign). The **Delegate trust substrate** — Ed25519-signed, identity-bound, capability-
declared, audit-chained connector actions — is the structural advantage no incumbent can copy.

**The honest caveat (verified in source):** the substrate currently _attests_ (signs + audits)
but does not yet _contain_ (credential-blindness, capability enforcement, sandbox). The wedge
is real but **must be built**, and **must not be marketed before it is built.**

## Success criteria

- A contributor can ship a connector for a typical REST API **without writing Python or
  touching cryptography** — fill in a declarative manifest, run a CLI, publish.
- The core team's per-connector maintenance cost is **zero** — discovery and trust are O(1).
- Running a community connector is **safe**: it cannot see credentials it wasn't granted,
  cannot exceed its declared capabilities, and every action is signed + audited.
- The trust claim made publicly is, at every moment, **true** — never ahead of the mechanism.

## Non-goals (for now)

- A visual workflow editor (n8n's canvas). This is about the _connector_ layer — the thing
  n8n is weakest at scaling and securing. The orchestration layer is a separate question.
- Re-implementing the whole automation platform before the connector marketplace exists.

## Decisions taken (see journal/0001)

1. Commit to the pivot; **write the architecture up first** (this brief + `02-plans/01-architecture.md`).
2. **Ship only the true (subset) trust claim** during the phased rollout.
3. **Yank the four published 0.1.0 packages**; restart clean under the plugin model.
