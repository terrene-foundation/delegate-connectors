# DECISION — Build to shipped API; defer conformance vectors

**Date:** 2026-05-27
**Phase:** /analyze → /todos gate
**Decider:** user (explicit, this session)

## Decisions (user-confirmed)

1. **Build to shipped-API reality.** Connector + runtime use the shipped
   `DelegateRuntime` + `DispatchSurface` + in-memory `AuditChainEngine` +
   `Ed25519Verifier` + Mailpit (real SMTP/IMAP). #1035's "real PACT engine + real
   Postgres audit" is treated as ASPIRATIONAL (the shipped SDK has neither). This
   is the only buildable path; it is still genuine no-mock integration.

2. **Defer conformance to a follow-up shard.** The canonical vectors are not in the
   wheel and sourcing them requires cross-repo access to kailash-py
   (`repo-scope-discipline.md`). User chose DEFER over authorizing cross-repo
   vendoring now.

## Deferred shard: conformance validation (value-anchor)

**Value-anchor (per `value-prioritization.md` MUST-2):** Conformance validation is
the contract that lets third-party + academic connector authors trust this
connector against the OSS spine without commercial access — the explicit purpose
of #1035 ("the conformance contract that disciplines the proprietary engine";
"any connector tests against it without commercial access"). It is HIGH value to
the workstream, deferred ONLY because the fixture is currently unreachable without
cross-repo authorization — NOT because it is low value.

**Re-pickup gate (MUST, per value-prioritization MUST-3):** when this shard is
picked up, re-validate the value-anchor AND confirm the cross-repo authorization
(vendor from kailash-py) OR the vectors have been shipped in a newer kailash wheel.

## Scope this cycle (/todos → /implement → /redteam)

Connector (`authenticate/read/write/invoke` + trust properties) + runtime wiring +
Mailpit Tier-2/3 integration + package layout + README correction. NOT conformance.
