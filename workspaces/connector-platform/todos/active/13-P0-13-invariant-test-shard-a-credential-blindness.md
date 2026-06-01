# P0-13 — Invariant TEST shard A — credential-blindness + unforgeability (cannot read ungranted secret; cannot sign arbitrary/unobserved/fabricated side effects)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~190 LOC
> **Depends on:** P0-09, P0-11
> **Implements:** architecture §2; brief security wedge; rules/zero-tolerance.md Rule 2

## What (≤3 sentences)

Cross-cutting invariant tests asserting the two highest-value security properties are REALLY closed (no fake containment, zero-tolerance Rule 2). Assert: a connector CANNOT read an ungranted secret (no os.environ path; BoundTransport exposes no credential via attribute, __dict__, serialization, or gc-referent path; ungranted credential class unobtainable); a connector CANNOT sign arbitrary bytes, a receipt for an unobserved side effect, OR a receipt for a FABRICATED side-effect result the broker never performed (the realistic production forge vector per security HIGH finding). Sweep the whatsapp INBOUND surface (webhook verify_token / app_secret) not just outbound send (security HIGH finding).

## Deliverable

A regression/security test module asserting credential-blindness (ungranted-secret unreachable by any attribute/serialization/referent path or env read, across outbound AND whatsapp inbound surfaces) and unforgeability (no connector-side signing; host refuses to sign arbitrary, unobserved, OR connector-fabricated side effects) across all four connectors.

## Files touched

- tests/regression/test_credential_blindness.py (new — cross-connector, incl. whatsapp inbound)
- tests/regression/test_unforgeability.py (new — cross-connector, incl. fabricated-result adversarial double)

## Invariants (MUST hold)

- a connector cannot read a secret it was not granted (no os.environ; BoundTransport has no credential accessor; not reachable via __dict__/vars/__getstate__/gc-referents; ungranted credential class unobtainable)
- the whatsapp INBOUND surface is swept: no .config/.verify_token/.app_secret reachable from the connector on the webhook ingress path (security HIGH finding — webhook.py:251 WebhookIngest.config)
- a connector cannot sign arbitrary bytes (no raw key, no signer thunk on the connector)
- the host refuses to sign a receipt for a side effect it did not observe
- ADVERSARIAL: a connector double that returns a fabricated SUCCESS result for a send the broker never performed gets NO signed receipt (or a receipt that fails verification because the host's observed-side-effect digest does not match) — the realistic production forge vector (security HIGH finding)
- tests assert REAL containment — no simulated isolation, no fake-blind stub (zero-tolerance Rule 2)

## Value anchor

Brief security wedge (architecture §2): credential-blindness and unforgeability are the two properties verified FALSE today. The plan MUST include explicit invariant TEST shards asserting a connector cannot read an ungranted secret and cannot sign arbitrary/unobserved/fabricated side effects. Per zero-tolerance Rule 2: no fake containment, no stubs, no simulated isolation.

## Acceptance criteria

- [ ] test proves a connector cannot read an ungranted secret (env + every attribute/serialization/referent path closed, outbound AND whatsapp inbound) across all four connectors
- [ ] test proves a connector cannot sign arbitrary bytes, an unobserved side effect, OR a connector-fabricated side-effect result
- [ ] tests assert real containment with no simulated isolation (zero-tolerance Rule 2)

## Test plan

Adversarial unit/regression: reach a credential from the connector's perspective via every attribute path on the injected handle (.config, .password, .token, dir(), vars(), __dict__, __getstate__, pickle, gc.get_referents) -> all denied/redacted; env read from inside the connector -> none exists; whatsapp inbound webhook verify_token/app_secret -> unreachable; obtain an ungranted credential class from the broker -> refused; connector-side signing -> no key/thunk; host sign bytes for an unobserved side effect -> refused; connector double returns a fabricated SUCCESS for a send the broker never performed -> NO receipt. All four connectors covered.
