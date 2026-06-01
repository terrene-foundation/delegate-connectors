# P0-02 — Build production RevocationChannel concrete (real signed denylist, fail-closed-on-stale AND cold-start) + DELETE NeverRevokedChannel

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~170 LOC
> **Depends on:** none — Wave 1 (no deps)
> **Implements:** architecture §7 Phase 0; architecture §2 (revocation ⚠️ placeholder); specs trust_primitive_interfaces (RevocationChannel); protocol-spec §6 Revocation

## What (≤3 sentences)

Build a production RevocationChannel concrete that consults a REAL revocation source (signed monotonic denylist: connector_id + version + fingerprint, hard fetch ceiling, fail-closed-on-stale, fail-closed-on-cold-start) and DELETE the NeverRevokedChannel->False placeholder from all four connectors. is_revoked() must return real state, never an unconditional False — including when no denylist has ever been successfully fetched (cold start / source-unreachable).

## Deliverable

A new shared `delegate_connectors_host/revocation.py` exporting a production RevocationChannel concrete (signed denylist consultation, fail-closed-on-stale, fail-closed-on-cold-start, fetch ceiling) satisfying the SDK Protocol; the four NeverRevokedChannel class definitions and __all__ exports removed.

## Files touched

- delegate_connectors_host/revocation.py (new shared host module)
- connectors/email/src/delegate_connectors/email/connector.py:102-112 (DELETE NeverRevokedChannel), :65 (remove from __all__)
- connectors/slack/src/delegate_connectors/slack/connector.py:116-125 (DELETE NeverRevokedChannel)
- connectors/telegram/src/delegate_connectors/telegram/connector.py:115-125 (DELETE NeverRevokedChannel)
- connectors/whatsapp/src/delegate_connectors/whatsapp/connector.py:132-142 (DELETE NeverRevokedChannel), :92 + __init__.py:34/109 (remove from __all__)

## Invariants (MUST hold)

- is_revoked() consults a real revocation source and returns REAL state (NEVER an unconditional False)
- fail-closed-on-stale: a denylist past its fetch ceiling treats the principal as potentially-revoked, not live
- fail-closed-on-cold-start: a never-successfully-fetched denylist (cold boot, no cached state, source unreachable) is treated as potentially-revoked, NOT live — this is the NeverRevoked->False failure mode in disguise and MUST be closed (security MEDIUM finding)
- denylist signature is verified before being trusted (signed monotonic denylist per protocol-spec §6)
- satisfies the SDK RevocationChannel Protocol structurally
- zero residual NeverRevokedChannel definitions or __all__ exports across all four connectors

## Value anchor

Architecture §7 Phase 0 explicitly names "delete the NeverRevokedChannel->False placeholder". §2 lists revocation as a ⚠️ documented placeholder structurally unsafe for untrusted contributors. The TEST shard P0-14 asserts revocation returns REAL state per zero-tolerance Rule 2, including the cold-start path.

## Acceptance criteria

- [ ] Production RevocationChannel concrete consults a real signed monotonic denylist and is fail-closed on BOTH stale AND cold-start/unreachable
- [ ] all four NeverRevokedChannel class definitions and their __all__ exports are deleted (grep returns zero hits)
- [ ] is_revoked() never returns an unconditional False on any path (live, stale, or cold)

## Test plan

Unit: a revoked (connector_id, version, fingerprint) on the signed denylist -> is_revoked True; a non-listed principal -> False; an invalid-signature denylist -> rejected (fail-closed); a denylist past the fetch ceiling -> fail-closed; a NEVER-fetched denylist / unreachable source -> fail-closed (cold start). Grep: zero NeverRevokedChannel occurrences across connectors/. Structural-conformance test: instance satisfies the SDK Protocol.
