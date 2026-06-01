# P0-15 — README + spec drift correction + present-tense honesty banner (scoped to the runtime refuse-to-sign-unobserved invariant; NOT the Phase-1 publish-time gate)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** no  ·  **Wire todo:** no  ·  **Est:** ~90 LOC
> **Depends on:** P0-11, P0-13, P0-14
> **Implements:** architecture §7 Phase 0; architecture §2 (true-subset claim); architecture §4 (publish-time vs runtime split); brief success criterion / decision #2; journal/0001 + 0002 DECISION

## What (≤3 sentences)

Correct README and spec drift to reflect the now-true Phase-0 claims, and add the present-tense honesty banner. After Phase 0 lands, credential-blindness and unforgeability are TRUE for the code tier; the banner must state the claim true at every moment and NOT over-claim sandbox/capability-enforcement (Phase 3), registry signing (Phase 2), the declarative tier (Phase 1), OR the record-and-replay publish-time acceptance gate (Phase 1). Only the RUNTIME refuse-to-sign-unobserved invariant (P0-08a/P0-13) is live at Phase 0 (completeness LOW finding — confirms the §4 publish-time/runtime split is honored).

## Deliverable

Updated README + spec docs reflecting the true post-Phase-0 trust subset (credential-blind + unforgeable + revocable for code connectors; capability-enforcement + sandbox still Phase 3; publish-time acceptance gate still Phase 1), plus a present-tense honesty banner.

## Files touched

- README.md (drift correction + honesty banner)
- specs/connector-contract.md (align with shipped trust-primitive concretes + delegate_host_protocol)
- specs/monorepo-layout.md (superseded note per architecture §0)

## Invariants (MUST hold)

- the public trust claim stated is TRUE at the moment Phase 0 lands — never ahead of the mechanism (brief success criterion + decision #2)
- credential-blindness + unforgeability + revocation are claimed for the code tier (now true); capability-enforcement + sandbox are NOT claimed (Phase 3)
- no marketing of registry signing / declarative tier (Phase 1-2 — not yet shipped)
- the honesty banner does NOT claim the record-and-replay PUBLISH-TIME acceptance gate (Phase 1) — only the RUNTIME refuse-to-sign-unobserved invariant (P0-08a) is live at Phase 0 (completeness LOW finding)
- spec docs match the shipped concretes (no stale NeverRevokedChannel / self-acquired-credential references)

## Value anchor

Architecture §7 Phase 0: "correct README drift" + the present-tense honesty banner. Brief success criterion: "The trust claim made publicly is, at every moment, true — never ahead of the mechanism" (decision #2). The most dangerous artifact the study found is claiming the full wedge before the mechanism exists.

## Acceptance criteria

- [ ] README + specs reflect the true post-Phase-0 trust subset with no over-claim of Phase 1-3 mechanisms (incl. no publish-time acceptance-gate claim)
- [ ] present-tense honesty banner present and accurate; scoped to the runtime refuse-to-sign-unobserved invariant
- [ ] no stale NeverRevokedChannel or self-acquired-credential references remain in docs

## Test plan

Doc review (intermediate-reviewer + gold-standards-validator): assert the honesty banner claims only the post-Phase-0 true subset (credential-blind + unforgeable + revocable for code tier, RUNTIME refuse-to-sign-unobserved only); assert NO claim of sandbox, capability-enforcement, registry signing, declarative tier, OR the publish-time acceptance gate; assert zero stale references to NeverRevokedChannel or self-acquired credentials. Cross-check claims against §2's true-subset wording.
