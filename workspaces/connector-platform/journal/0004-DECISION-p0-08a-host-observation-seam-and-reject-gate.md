---
type: DECISION
date: 2026-06-02
created_at: 2026-06-02T10:20:00Z
author: co-authored
session_id: term-21832
session_turn: 20
project: connector-platform
phase: implement
topic: P0-08a host-observation seam built; adversarial review surfaced + closed the §5 reject-suite producer gap in-shard
tags:
  [
    phase-0,
    p0-08a,
    forge-oracle,
    host-observation,
    canonical-signing-bytes,
    reject-suite,
    redteam,
    adversarial-review,
  ]
---

## Context

Wave 3 of Phase 0. P0-08a builds the NET-NEW **host-observation seam** — the first of the
three composed mechanisms that close the forge oracle architecture §2 verifies open today
(the other two are P0-08b host-side signing and P0-09/P0-11 connector-invocation-ownership
removal). Depends on the landed P0-04/05/06/07 primitives (Waves 1+2, merged PR #22/#23).

The forge being closed: today a connector both _performs_ the side effect (the action thunk
runs inside `connector.py`'s `write()`/`read()`) AND _builds + signs_ the receipt — so it can
return a fabricated "success" for a send that never happened and a naive host signer would
sign it. P0-08a relocates side-effect **invocation + observation** to the host.

## Decisions

1. **Built `delegate_connectors_host/dispatch_observation.py`** — `DispatchObservationSeam`.
   The host invokes the brokered side effect through the `BoundTransport` handle
   (`send`/`fetch`), captures its OWN observation, applies the connector's _pure_ `summarize`
   projection to the host-captured value, stamps a host-generated `action_id`/`read_id` +
   P0-05 fixed-width-microsecond `observed_at`, derives canonical bytes via the P0-04 shared
   helpers, and **refuses to derive bytes for any side effect it did not itself observe**.

2. **Capability = ticket object-identity.** `ObservedSideEffect` is a `frozen(eq=False)`
   dataclass registered in a per-seam `WeakKeyDictionary` keyed by object identity. The seam
   is the sole minter; a fabricated, copied-field, wrong-kind, or foreign-seam ticket is a
   different identity, absent from the ledger → `UnobservedSideEffectError`. This is the
   structural forge closure — there is no API path turning a connector-supplied result into
   signable bytes without the host having invoked the brokered handle.

3. **Scope held to observation only** (matching the P0-07 broker precedent): no Ed25519
   signing (P0-08b), no connector wiring (P0-09/P0-11). The seam lands as an intentional
   transitional orphan with no production call site yet, unit-tested standalone. Zero kailash
   spine edits (the spine is a separate repo — repo-scope discipline); the seam composes
   around the SDK `DispatchSurface` and reaches the frozen helpers only via the host's own
   `signing_bytes`.

4. **Adversarial review (workflow `wf_0dd3f5d9-ac3`, 4 lenses) surfaced one real defect →
   fixed in-shard.** Three independent lenses (forge-attack HIGH with running exploits,
   spec-conformance MEDIUM, correctness LOW) converged: the canonical-bytes producer enforced
   **none** of the frozen spec's §5 reject suite. The shipped `kailash.trust._json.
canonical_json_dumps` is `json.dumps(...)` WITHOUT `allow_nan=False` and with no
   integer-domain / key-type checks, so the producer silently emitted `NaN`/`Infinity`/float/
   ≥2^53-int/non-string-key bytes that "look signed" but verify nowhere (a Rust `serde_json`
   verifier rejects `NaN` on parse; a JS `JSON.parse` corrupts ≥2^53). The todo's own invariant
   (line 25, "canonical bytes conform to §1–§6") required this. Per `autonomous-execution.md`
   Rule 4 (same-bug-class gap within shard budget → fix now, filing a follow-up is BLOCKED),
   closed it in-shard rather than deferring.

5. **Fix placed at the producer chokepoint, NOT the seam alone.** New
   `delegate_connectors_host/canonical_domain.py::assert_canonical_signing_domain` enforces
   §1.2–§1.5 + §5 (reject any float/NaN/Inf, |int|≥2^53, non-string key, lone surrogate,
   recursively). Wired into BOTH `build_action_signing_bytes` and `build_read_signing_bytes`
   (the boundary §1.4 designates — "the canonicalizer MUST enforce this at the connector
   boundary"). This fixes the gap for the new seam AND the four existing connectors in one DRY
   place, with zero spine edits and without re-implementing the canonical ENCODING (key
   ordering/escaping stay the frozen encoder's job). It enforces the spec's normative §5 suite
   — conformance, not divergence; a conforming Rust producer enforces the same §5.

6. **Smaller hardening from the review, applied in-shard:** the highest-value missing test
   (brokered call that _raises_ mints no ticket — the runtime sibling of "a send that never
   happened", guarding a future try/except refactor from silently re-opening the forge); the
   §5 reject suite added as the spec's SECOND conformance gate (was enforced nowhere); Vector B
   reproduced through the seam (locks `_fixed_width`'s non-zero-µs branch end-to-end); the
   reserved-kwarg shadowing (`signer_delegate_id`/`attester_delegate_id` not forwarded)
   documented + tested; `Summarize` re-exported from the package surface; summarize-payload
   provenance recorded as connector-controlled-by-design (tightening deferred to P0-09/P0-11).

## Consequences

- **593 tests pass** (host 148: +42 this shard; email 70, slack 110, telegram 122, whatsapp
  143 — all green, confirming the producer-gate change broke no connector). Vectors A + C
  reproduce the frozen §6 bytes byte-for-byte through the seam; Vector B through the seam.
- User-flow walk receipt (verbatim, as P0-08b / a wiring author invokes it):
  - host invokes the real brokered send → derives `{action_id, observed_at, payload,
signer_delegate_id}` (the §2.1 receipt pre-image, distinct from the audit-event shape);
  - a fabricated success ticket for a send that never happened → host produces NO bytes (refused);
  - a NaN payload → refused at the producer boundary before any ticket is minted;
  - read path → `{attester_delegate_id, manifest, observed_at, read_id}`.
- **Open upstream item (NOT acted on — needs human gate per `upstream-issue-hygiene.md`):**
  `kailash.trust._json.canonical_json_dumps` still lacks `allow_nan=False` + the §1.3 integer
  cap for ANY other consumer in the kailash ecosystem. This repo's producer gate closes it at
  our boundary, but the spine-side fix belongs upstream against `kailash-py`. Recommend filing.
- Critical-path position unchanged: `… → P0-08a → P0-08b → P0-10a → …`. Next shard: P0-08b
  (host holds the Ed25519 key; signs ONLY the bytes this seam derived).

## For Discussion

1. The §5 reject gate was placed in the shared `build_*_signing_bytes` chokepoint (fixing the
   connectors too) rather than seam-locally as the forge-attacker lens recommended. The trade:
   broader blast radius now (all four connectors' producers change behavior) vs. leaving them
   non-conformant until P0-11 replaces them. Given their payloads are already conformant (445
   connector tests stayed green), the chokepoint placement carried no behavioral cost — but was
   it the right call to touch the P0-04 surface in a P0-08a shard, or should the gate have
   waited for an explicit P0-04 amendment?
2. If we had shipped P0-08a WITHOUT the adversarial review workflow, the §5 producer gap would
   have ridden into P0-08b — where the host would have _signed_ `NaN`/`Infinity` receipts that
   no Rust/JS verifier can check. How much later would a publish-time conformance vector have
   caught it, versus the runtime adversarial double in P0-13 — and would either have caught the
   _silent-corruption_ (≥2^53 int) case, which still produces parseable-but-wrong bytes?
3. The forge closure rests on `summarize` being a pure projection of the host-captured return.
   The seam owns the INVOCATION and OBSERVATION but lets the connector own the payload SHAPE. Is
   deferring payload-shape provenance hardening to P0-09/P0-11 the right boundary, or does a
   malicious-but-pure `summarize` (returns a constant ignoring its input) constitute a residual
   forge the P0-13 adversarial test must explicitly probe?
