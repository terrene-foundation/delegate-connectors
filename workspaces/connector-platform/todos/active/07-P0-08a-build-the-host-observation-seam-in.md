# P0-08a — Build the host-observation seam in DispatchSurface (host invokes the brokered side effect, derives canonical bytes, refuses unobserved)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~180 LOC
> **Depends on:** P0-04, P0-05, P0-06, P0-07
> **Implements:** architecture §3.5 layer 2 (b); architecture §2 (unforgeability false); specs host_signing_constraints; specs/canonical-signing-bytes.md §3; protocol-spec §2 (receipt vs audit-event pre-image); value-prioritization MUST-1

## What (≤3 sentences)

Build the NET-NEW host-observation mechanism: the host (DispatchSurface layer) INVOKES the brokered side effect via the BoundTransport handle and CAPTURES its own observation of the return value, derives the canonical bytes from that host-observed result via the shared P0-04 helpers, and REFUSES to produce bytes for any side effect it did not observe. This seam does NOT exist today (verified: the action thunk runs INSIDE the connector's write()/read() at connector.py:343, and the connector builds the canonical bytes). This is the standalone observation mechanism with its own unit tests; signing (the key) is P0-08b. Split out of the original P0-08 per capacity HIGH finding (6 invariants + greenfield seam + 3-4 hops was over the ceiling on two axes).

## Deliverable

A host-observation path in/around DispatchSurface: the host invokes the brokered side effect through the BoundTransport handle, captures the host-observed return, derives canonical bytes via the shared P0-04 helpers (with the P0-05 microsecond timestamp), and refuses to derive bytes for any side effect it did not itself invoke/observe.

## Files touched

- delegate_connectors_host/dispatch_observation.py (new — host-observation seam over DispatchSurface)
- connectors/email/src/delegate_connectors/email/connector.py:343 (the action-thunk-runs-in-connector path the seam relocates — connector loses ownership of the side-effect invocation, see P0-09)

## Invariants (MUST hold)

- the brokered side effect is INVOKED by the HOST (DispatchSurface via the BoundTransport handle), and the value used to derive canonical bytes is the host-captured return of that host-invocation — the connector never supplies the to-be-derived side-effect result (security CRITICAL finding)
- DispatchSurface derives canonical bytes from the HOST-OBSERVED side effect (specs host_signing_constraints)
- the host REFUSES to derive bytes for an unobserved side effect (no sign-arbitrary-bytes, no sign-a-delivery-that-never-happened) — including refusing when a connector returns a fabricated SUCCESS result for a send the broker never performed
- canonical bytes conform to canonical-signing-bytes §1-§6 (unchanged) + carry the §3 microsecond timestamp from P0-05
- the host-side RECEIPT-byte derivation is DISTINCT from the spine DispatchSurface audit `signer=` slot (different pre-image per protocol-spec §2: receipt = {action_id,observed_at,payload,signer_delegate_id} vs audit-event = {event_type,event_payload,signer_delegate_id}); this seam lands entirely in a host module + the connector write()/read() path with ZERO edits to the kailash spine (kailash-py is a separate repo — repo-scope-discipline) (completeness MEDIUM / dual-signer finding)

## Value anchor

Architecture §3.5 layer 2 (b): handing the connector a signer thunk is a FORGE ORACLE; signing MUST move host-side. The observation seam is the prerequisite — the host can only sign over what it itself observed. §2 lists unforgeability as FALSE today. HIGHEST user-value (value-prioritization MUST-1). Brief success criterion: the public trust claim true at every moment.

## Acceptance criteria

- [ ] the host invokes and observes the brokered side effect; canonical bytes are derived only from the host-observed return
- [ ] the host refuses to derive bytes for any unobserved or connector-fabricated side effect
- [ ] the receipt pre-image is distinct from the spine audit signer pre-image; zero kailash spine edits

## Test plan

Unit: the host invokes a brokered send via the BoundTransport handle and derives canonical bytes ONLY from the host-captured return; host.derive(arbitrary_bytes) with no observed side effect -> refused; a connector double returning a fabricated SUCCESS result for a send the broker never performed -> the host produces NO bytes (refuses, because its own observation digest does not match). Assert the receipt pre-image is the §2 receipt shape, NOT the audit-event shape; assert no kailash/ source is touched (grep). BUILD half of the cannot-forge invariant TEST in P0-13.
