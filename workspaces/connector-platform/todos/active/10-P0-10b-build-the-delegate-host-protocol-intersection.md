# P0-10b — Build the delegate_host_protocol intersection gate (S∩H, bind at max, loud load-time refusal, portable 'protocol.unsupported' kind)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~120 LOC
> **Depends on:** P0-10a
> **Implements:** architecture §3.3; architecture §7 Phase 0; specs host_protocol_contract; protocol-spec §8 §9

## What (≤3 sentences)

Build the delegate_host_protocol intersection gate on top of the P0-10a factory: read the connector's declared delegate_host_protocol integer/range S, compute S∩H against the host's supported set H, LOAD iff non-empty (bind at max(S∩H)), ELSE REFUSE with a loud load-time error naming connector kind + connector range + host range. The error MUST surface the portable `kind` string 'protocol.unsupported' (protocol-spec §9) as a language-neutral attribute consistent with the SDK error-taxonomy surface — NOT a bespoke local exception class name (so the Rust dc-enterprise tier and the conformance driver, which assert on `kind`, do not mismatch). Split out of the original P0-10 per capacity HIGH finding — this is net-new control-flow with its own error taxonomy, distinct from the mechanical ceremony.

## Deliverable

The delegate_host_protocol intersection gate in/around connector_builder.py: S∩H computation, max-binding, loud load-time refusal with a portable `kind == 'protocol.unsupported'` attribute naming both ranges, and a documented axis-separation from the SDK pin.

## Files touched

- delegate_connectors_host/connector_builder.py (extend with the protocol-intersection gate)

## Invariants (MUST hold)

- reads connector-declared delegate_host_protocol; computes S∩H against the host's supported set H
- LOAD iff S∩H non-empty; bind at max(S∩H); ELSE loud LOAD-TIME refusal
- the refusal exposes a portable `kind == 'protocol.unsupported'` attribute (protocol-spec §9, language-neutral, asserted by the conformance driver) consistent with the SDK error-taxonomy surface — NOT a bespoke local exception class name (completeness LOW finding)
- the refusal message names connector kind + connector's declared range + host's range
- delegate_host_protocol axis is documented as SEPARATE from the SDK pin kailash>=2.28,<3 (never collapse them)

## Value anchor

Architecture §3.3 + §7 Phase 0: "ship ... + delegate_host_protocol". Converts ~20 unversioned spine couplings into ONE versioned contract — a spine change becomes a coordinated migration, not a silent thousands-wide break. The loud load-time refusal is the structural mechanism (Terraform protocol_versions 5.0/6.0 model).

## Acceptance criteria

- [ ] an unsupported delegate_host_protocol range triggers a loud load-time refusal naming kind + both ranges
- [ ] the refusal exposes a portable `kind == 'protocol.unsupported'` attribute (not a bespoke local exception name), consistent with the SDK/conformance error surface
- [ ] delegate_host_protocol is documented as a distinct axis from the SDK dependency pin

## Test plan

Unit: a connector declaring a protocol range overlapping H -> loads, bound at max(S∩H); a disjoint range -> raises a loud load-time error exposing `.kind == 'protocol.unsupported'` (portable attribute) and a message naming kind + connector range + host range; assert the SDK pin and delegate_host_protocol are independent axes. BUILD half of the protocol-gate invariant TEST in P0-14.
