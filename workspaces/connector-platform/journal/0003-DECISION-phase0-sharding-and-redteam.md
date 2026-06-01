---
type: DECISION
date: 2026-06-01
created_at: 2026-06-01T12:00:00Z
author: co-authored
session_id: term-21832
session_turn: 60
project: connector-platform
topic: Phase 0 (decoupling foundation) sharded into 15 implement-ready todos + 3-lens redteam disposition
phase: todos
tags:
  [
    phase-0,
    sharding,
    credential-broker,
    host-side-signing,
    forge-oracle,
    redteam,
    capacity-budget,
  ]
---

## Context

The owner approved starting Phase 0 (the decoupling foundation). Phase 0 is the most load-bearing,
most security-critical build in the project — it converts the three trust properties architecture §2
verifies FALSE today (credential-blindness, unforgeability, revocation) into true ones. Per the
per-session capacity budget, a load-bearing security refactor across 4 connectors + core primitives
MUST be sharded at `/todos` time. Planning ran as workflow `wf_b449385b-910` (10 agents): 5 grounding
agents (4 connectors + the frozen-spec/SDK surface, structured facts with file:line), 1 synthesis,
3 adversarial red-team lenses, 1 revise pass.

## Decisions

1. **Phase 0 sharded into 15 implement-ready todos** (`todos/active/00-…` index + `01-…`–`15-…`),
   each within the capacity budget on all axes (≤500 LOC load-bearing, ≤5–10 invariants, ≤3–4
   call-graph hops, ≤3-sentence describable). Grounded in real `file:line` (e.g. `connector.py:269`
   raw key, `smtp.py:164`/`imap.py:76`/`web_api.py:74` env reads, `connector.py:343` action thunk,
   `webhook.py:252` WhatsApp ingress `.config`).

2. **Forge-oracle closure is the spine of the plan.** The red-team's two CRITICAL findings: removing
   the connector's raw Ed25519 key (P0-08b) and signer thunk (P0-08a) is _necessary but not
   sufficient_ — a connector can still return a fabricated "success" for a send the broker never
   performed, and a naive host-side signer would sign it (the exact "sign a delivery that never
   happened" forge of architecture §3.5b). Closed via **three composed mechanisms**: P0-08a (host
   invokes + observes the brokered side effect, refuses to derive bytes for the unobserved), P0-08b
   (host signs only P0-08a-derived bytes), P0-09/P0-11 (connector loses action-invocation ownership
   at `connector.py:343`). P0-13 proves all three via an adversarial fabricated-result test.

3. **Two over-ceiling shards split** (capacity HIGH findings): original P0-08 (host-side signing)
   bundled 6 load-bearing concerns + a greenfield observation seam + 3–4 hops → split into P0-08a
   (observation seam) + P0-08b (key relocation). Original P0-10 bundled the ~10-concrete compose
   ceremony + the protocol-intersection gate (unrelated control-flow) → split into P0-10a (factory)
   - P0-10b (protocol gate).

4. **`.config` leak sweep extended to the WhatsApp inbound path** (security HIGH): the leak is not
   only outbound (`smtp.py:258`, `web_api.py:182`, etc.) — `webhook.py:252` exposes the inbound
   `verify_token`/`app_secret`. P0-06/P0-07/P0-11 scope + the P0-13 credential-blindness test now
   sweep the ingress surface, not just `send`.

5. **Registry / Item-1 / Item-4 / Item-5 are Phase 2–3, not Phase 0.** Corrects the prior session's
   "open questions for the human" framing: these axes do NOT surface during Phase 0. P1–P4 are tracked
   as milestone placeholders (`implement_ready=false`), expanded at their own `/todos` when each
   design gate opens — not detailed now (authority-before-mechanism; journal/0002 decision #4).

6. **Plan STOPS at the human gate.** No code is written until the owner approves this plan (the
   `/todos` structural gate, per autonomous-execution.md).

## Consequences

- Critical path: `P0-04 → P0-05 → [P0-06+P0-07] → P0-08a → P0-08b → P0-10a → P0-10b → P0-11 → [P0-13+P0-14] → P0-15`, executed as 9 parallelizable waves (Wave 7 = the 4 connector refactors, worktree-isolated, slack-first then email+telegram parallel then whatsapp dedicated).
- P0-05 (12-site isoformat migration) is an atomicity guard — one commit, or cross-impl receipt verification with the Rust `dc-enterprise` tier breaks 100%.
- The frozen crypto core (`specs/canonical-signing-bytes.md` v1) is conformed-to, never edited — no shard touches §1–§6.
- On approval: `/implement` executes Wave 1 (P0-01, P0-02, P0-04, P0-06 in parallel).

## For Discussion

1. The plan creates a new host-side package (`delegate_connectors_host/`) for the broker and signer,
   keeping the connectors as pure consumers. Is a separate top-level package the right home, or should
   the host surface live under the existing `kailash.delegate` SDK boundary — and does that choice
   change who owns the `from_env()` credential-acquisition responsibility?
2. The red-team's fabricated-result test (P0-13) asserts the host refuses to sign a side effect the
   broker never performed. **If we had shipped the original single-shard P0-08 (key removal only)**,
   how many connectors would have passed every existing test while still carrying a host-side forge
   oracle — and would a publish-time conformance vector have caught it, or only a runtime adversarial
   double?
3. Wave 7 sequences whatsapp as a dedicated pass because its ~7-invariant load (4 secrets / 3 files +
   window + template gate + PII floor) exceeds a simultaneous fan-out's attention budget. Is the
   right response to serialize it, or to split whatsapp's own refactor into two shards (outbound
   send vs inbound webhook/redaction) so it rejoins the parallel wave?
