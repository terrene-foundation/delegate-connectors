# Phase 0 — Decoupling Foundation (todo index)

**Status:** PROPOSED — awaiting owner approval of this plan (the `/todos` structural gate). No code until approved.
**Date:** 2026-06-01
**Plan provenance:** grounded + sharded + red-teamed via workflow `wf_b449385b-910` (10 agents). Disposition in `journal/0003`.
**Source of truth:** architecture §7 (`../../02-plans/01-architecture.md`); frozen crypto core `specs/canonical-signing-bytes.md` (v1 — conform, never edit).

## Goal (one line)

Make the trust wedge **real**: convert the three properties architecture §2 verifies FALSE today —
**credential-blindness**, **unforgeability**, **revocation** — into true ones, so the public claim
matches the mechanism (brief success criterion: _"the trust claim made publicly is, at every moment, true"_).

## What Phase 0 ships (architecture §7 — nothing more)

1. Production trust-primitive concretes (`KnowledgeLedger`, `RevocationChannel`, `AuthVerifier`) + **delete** `NeverRevokedChannel→False`.
2. The versioned `connector_builder()` factory + `delegate_host_protocol` load-time gate (absorbs the ~246-LOC compose ceremony each connector hand-copies).
3. The credential broker (host owns `from_env()`, injects an opaque non-introspectable `BoundTransport`) + host-side signing (host observes the brokered side effect and signs over its _own_ captured result).
4. Refactor of the 4 reference connectors (email, slack, telegram, whatsapp) onto all of the above.
5. README + spec drift correction + present-tense honesty banner.

## NOT Phase 0 (do not build here)

The signed **registry**, the **declarative/manifest** tier, the **sandbox**, and the parked axes —
**Item-1** (`connector_kind` namespacing), **Item-4** (capability lattice), **Item-5** (registry
signing / transparency log) — are **Phase 1–3**. Their subsystems do not exist; freezing their
contracts now is the authority-before-mechanism trap (journal/0002 decision #4). **They do not
surface during Phase 0** — there is nothing for the owner to decide on them at this gate.

## The forge-oracle closure (why this plan is shaped the way it is)

Removing the connector's raw signing key is **necessary but not sufficient**. A connector can still
return a _fabricated_ "success" for a send the broker never performed, and a naive host-side signer
would sign it — a relocated forge oracle. The plan closes this with **three composed mechanisms**:

- **P0-08a** — the host _invokes and observes_ the brokered side effect; refuses to derive bytes for anything it did not observe.
- **P0-08b** — the host holds the key and signs _only_ P0-08a-derived bytes.
- **P0-09 / P0-11** — the connector loses ownership of the action invocation (`connector.py:343`), so it cannot hand the host a fabricated result to sign.

**P0-13** proves all three hold together via an adversarial connector that returns a fake success → host refuses to sign.

## Milestone forest

| ID  | Milestone                               | Ready?           | Anchor                                                          |
| --- | --------------------------------------- | ---------------- | --------------------------------------------------------------- |
| P0  | Decoupling foundation                   | ✅ sharded below | Brief success criteria §2 — the real wedge                      |
| P1  | Declarative tier (manifest interpreter) | ⏳ placeholder   | Arch §7 Phase 1 — safe community on-ramp                        |
| P2  | Gated code discovery + signed registry  | ⏳ placeholder   | Arch §7 Phase 2 — Item-1/Item-5 live here                       |
| P3  | The sandbox (gVisor/seccomp)            | ⏳ placeholder   | Arch §7 Phase 3 — Item-4; full "run any connector safely" claim |
| P4  | Operational hardening                   | ⏳ placeholder   | Arch §7 Phase 4 — standing supply-chain response                |

P1–P4 expand at their own `/todos` when each phase's design gate opens. They are tracked, not detailed.

## Value ranking within P0 (value-prioritization MUST-1)

**Highest user-value:** the credential-broker (**P0-07**) + `BoundTransport` (**P0-06**) +
host-observation/signing chain (**P0-08a / P0-08b**). These convert the marketed narrow-subset claim
into the real credential-blind + unforgeable wedge — the brief's core success criterion and the only
thing no incumbent (n8n/Zapier/Make/Airbyte) ships. The security-CRITICAL fix means the observation
seam structurally _cannot_ precede the broker, which also enforces this value ordering.

## Critical path (longest dependency chain)

`P0-04 → P0-05 → [P0-06 + P0-07] → P0-08a → P0-08b → P0-10a → P0-10b → P0-11 → [P0-13 + P0-14] → P0-15`

## Parallelizable waves (autonomous execution; worktree-isolated where noted)

- **Wave 1** (no deps): `P0-01` ledger · `P0-02` revocation + delete NeverRevoked + cold-start fail-closed · `P0-04` extract shared signing helpers + LOC-invariant test · `P0-06` BoundTransport (closure-capture hardening).
- **Wave 2:** `P0-05` atomic 12-site isoformat migration (needs P0-04) · `P0-07` credential broker (needs P0-06; all 4 whatsapp secrets incl. dual-path PII-HMAC).
- **Wave 3:** `P0-08a` host-observation seam (needs P0-04, P0-05, P0-06, P0-07 — the host can only sign what it itself brokered).
- **Wave 4:** `P0-08b` host-side signer (needs P0-08a).
- **Wave 5:** `P0-10a` compose-ceremony factory (needs P0-04, P0-07, P0-08b). `P0-09` seam spec finalized here.
- **Wave 6:** `P0-10b` protocol-intersection gate (needs P0-10a).
- **Wave 7 — the big parallelization:** `P0-11` connector refactors, each folding its P0-09 seam. **Sequence:** slack first (cleanest baseline) → email + telegram parallel → **whatsapp as its own dedicated pass** (~7-invariant load must not compete for attention). Worktree-isolate per `agents.md` (disjoint packages; one version owner).
- **Wave 8:** `P0-13` + `P0-14` invariant tests in parallel (disjoint test modules).
- **Wave 9:** `P0-15` docs + honesty banner last (claim becomes true only after the mechanism lands).

## Atomicity guard

`P0-05` (12-site isoformat migration) MUST land as ONE commit — a partial merge silently breaks 100%
of cross-impl receipt verification with the Rust `dc-enterprise` tier (specs notes #2). The fix lives
at the 12 call sites (each passes `observed_at` as a pre-formatted string); P0-04 first gives a stable
shared helper to run the vectors against.

## Red-team disposition (workflow `wf_b449385b-910`)

3 lenses (capacity / completeness / security), all `approve-with-edits`; 20 findings, **6 CRITICAL/HIGH
all resolved** in the revise pass. Key resolutions: two over-ceiling shards split (`P0-08`→`a/b`,
`P0-10`→`a/b`); the forge-oracle CRITICALs closed via the three-mechanism chain above; the `.config`
leak sweep extended to the WhatsApp **inbound** webhook surface (`webhook.py:252` — `verify_token`/`app_secret`).
Full disposition: `journal/0003`.
