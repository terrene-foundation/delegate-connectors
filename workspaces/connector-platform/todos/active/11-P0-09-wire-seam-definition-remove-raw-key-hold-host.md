# P0-09 — WIRE seam definition: remove raw-key hold + host-owned action invocation + ledger/revocation rebind (specification of the per-connector seam folded into P0-11 worktrees)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** YES  ·  **Est:** ~60 LOC
> **Depends on:** P0-01, P0-02, P0-08a, P0-08b, P0-10a
> **Implements:** architecture §2; architecture §7 Phase 0; specs abc_members per connector; rules/autonomous-execution.md Build-vs-Wire; rules/autonomous-execution.md MUST-1 (per-connector sharding)

## What (≤3 sentences)

Define the per-connector WIRE seam that each P0-11 worktree applies: remove the raw signing_key from connector __init__ and instance state; relocate ownership of the side-effect (action/query thunk) INVOCATION to the host (P0-08a) so the connector no longer invokes the side effect whose result is signed; bind the production KnowledgeLedger (P0-01) and RevocationChannel (P0-02) via the ledger/revocation properties; remove the connector-side _sign path. Per capacity MEDIUM finding, this seam is NOT a separate all-4-connectors-at-once pass — it is FOLDED INTO each connector's P0-11 worktree sub-shard (edited once per connector, in that connector's own worktree, with that connector's four-tier suite as the live feedback loop). This shard is the seam SPECIFICATION + the cross-connector invariant set the P0-11 worktrees must each satisfy.

## Deliverable

The per-connector WIRE seam specification (raw-key removal + host-owned action invocation + ledger/revocation rebind + _sign removal) applied INSIDE each P0-11 worktree, plus the cross-connector invariant set every worktree must satisfy.

## Files touched

- connectors/email/src/delegate_connectors/email/connector.py:246,258-261,269,273,281-287,291-293,343 (applied within email's P0-11 worktree)
- connectors/slack/src/delegate_connectors/slack/connector.py:259,289,293,302-306,313 (applied within slack's P0-11 worktree)
- connectors/telegram/src/delegate_connectors/telegram/connector.py:259,284,288,297-301,308 (applied within telegram's P0-11 worktree)
- connectors/whatsapp/src/delegate_connectors/whatsapp/connector.py:286,318-323,342,346,354-360,366,443,486 (applied within whatsapp's P0-11 worktree)

## Invariants (MUST hold)

- no connector __init__ accepts or holds a raw Ed25519PrivateKey (unforgeability — connector holds neither key nor thunk)
- the brokered side effect is INVOKED by the HOST (DispatchSurface via the BoundTransport handle per P0-08a), and the value signed is the host-captured return — the connector NEVER supplies the to-be-signed side-effect result; a connector returning a fabricated SUCCESS result for a send the broker never performed yields NO signed receipt (security CRITICAL finding — closes the connector-controlled-action-thunk forge surface at connector.py:343)
- ledger property returns the production KnowledgeLedger (P0-01); revocation property returns the production RevocationChannel (P0-02)
- no NeverRevokedChannel instance remains bound on any connector
- the connector-side _sign helper is removed; signing is host-side only (P0-08b)
- auth_verifier property still returns the SDK Ed25519Verifier (P0-10a binding); the 7 ABC members + connector_id/connector_kind/requires_capabilities class attrs preserved
- this seam is applied PER-CONNECTOR inside the P0-11 worktree (one file's seam per worktree, NOT four files in one pass — capacity MEDIUM finding)

## Value anchor

Architecture §2: removes the connector.py:269 raw-key hold (unforgeability FALSE), the connector.py:273 NeverRevokedChannel bind (revocation placeholder), AND the connector-controlled action-invocation forge surface at connector.py:343. Build-vs-Wire MUST: this is the WIRE seam, now per-connector to avoid the 4-file pattern-match-poisoning the capacity rule guards against.

## Acceptance criteria

- [ ] no connector holds a raw Ed25519 key or a signer thunk (grep clean, per connector)
- [ ] the host owns the side-effect invocation; a connector-fabricated result yields no signed receipt
- [ ] ledger/revocation properties return the production concretes; no NeverRevokedChannel remains
- [ ] existing receipt-identity-binding regression tests pass with host-side signing
- [ ] the seam is applied per-connector inside the P0-11 worktrees, not as a separate all-4 pass

## Test plan

Per connector (inside its P0-11 worktree, test_connector + regression): assert __init__ no longer accepts a signing_key; assert the connector no longer invokes the side effect whose result is signed (host owns invocation); assert ledger/revocation properties return the production concretes; assert no NeverRevokedChannel import/instance; assert a fabricated connector result yields no receipt. Grep per connector: zero `self._signing_key` and zero NeverRevokedChannel. Regression: test_receipt_identity_binding passes (host-signed). The seam invariants are verified per-worktree by P0-11's four-tier suites + cross-cut by P0-13.
