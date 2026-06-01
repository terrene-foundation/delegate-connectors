---
type: DECISION
date: 2026-06-01
created_at: 2026-06-01T00:00:00Z
author: co-authored
session_id: term-21832
session_turn: 30
project: connector-platform
topic: Redteam of the architecture + freeze of the receipt-signing crypto core (protocol v1)
phase: redteam
tags:
  [
    protocol,
    signing,
    interop,
    rust,
    dc-enterprise,
    freeze,
    redteam,
    canonical-json,
  ]
---

## Context

PR #19 captured the connector-platform architecture (Architecture C) + a first-pass normative
protocol spec. The owner asked to redteam it and to make the spec ironclad so the Rust
`dc-enterprise` tier can align. Two adversarial workflows ran (`wf_405bd2d6-850` redteam,
`wf_faa33b0e-65b` freeze-hardening), verifying every claim against source.

## Decisions

1. **Redteam verdict accepted:** design `approve-with-edits`; cross-impl alignment
   `needs-revision`. The architecture was a design narrative, not a wire contract. Applied: narrowed
   the trust over-claims verified FALSE in source (credential-blindness, unforgeability,
   capability-bounded), reframed the broker as a host-side signing-surface refactor, added the
   conformance-vector dependency + the OSS↔enterprise boundary.
2. **Receipt-signing crypto core FROZEN v1** (`specs/canonical-signing-bytes.md`): pinned the
   canonical-JSON rule (code-point key order, NOT RFC 8785/JCS), fixed-width microsecond timestamp,
   raw-64-byte signature wire form, + 9 edge-case pins the hardening surfaced (big-int float
   coercion, silent NaN, string-only keys, escape table, lone-surrogate, duplicate-key, no
   normalization). 5 reproducible vectors, all verified to round-trip.
3. **JS consumers in scope** (owner) → signed-integer domain `[-(2^53-1), 2^53-1]`.
4. **Items 1/4/5 (owner/kind, capability lattice, registry signing) NOT frozen** — they are wire
   contracts for subsystems (registry/manifest/sandbox) that do not exist; freezing them would be
   the authority-before-mechanism trap. Deferred to Phase 0 subsystem design.
5. **Ship the frozen core now; design subsystems in Phase 0** (owner). The 4 published 0.1.0
   packages were **yanked** (owner). PR #19 merged to `main` (`c370812`).

## Consequences

- Rust `dc-enterprise` aligns to `canonical-signing-bytes.md` (v1) + the §6 vectors — spec +
  vectors, never the Python source. Stable `main` URLs delivered to the owner.
- Phase 0 (decoupling foundation) is the next build, gated on the owner's go.
- The registry/owner-identity/capability-lattice spec freezes incrementally as Phase 0 builds each
  subsystem.

## For Discussion

1. The freeze pass found that "lexicographic key sort" silently diverges from RFC 8785/JCS on
   astral keys — if we had shipped the spec saying "canonical JSON per JCS," how many cross-impl
   verification failures would the Rust team have hit before tracing it to an emoji key?
2. We capped integers at `2^53-1` for JS safety. If JS consumers were later removed from scope,
   would re-widening to `2^64-1` be worth a `protocol_version` bump, or is the narrower cap
   strictly better to keep regardless?
3. Items 1/4/5 were left unfrozen because their subsystems don't exist. What is the evidence that
   freezing a contract ahead of its mechanism (vs after) actually causes drift — and does the
   crypto core (frozen from shipped code) prove the inverse?
