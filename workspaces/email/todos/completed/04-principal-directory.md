# Todo 04 — Principal resolution / directory wiring

**Implements:** `specs/email-connector.md` § Principal resolution + § Unknown-sender
**Type:** Build · **Capacity:** single shard (~80 LOC, 3 invariants)
**Depends:** 01

## Do

- `src/delegate_connectors/email/directory.py` — resolve a normalized email address
  to a `Principal` via the shipped `PrincipalDirectory`. v0 = exact-match lookup of
  the normalized `From:`/recipient address.
- Define the address-normalization rule (lowercase, strip, RFC-5322 display-name
  stripping) used consistently for resolution.

## Invariants

1. Exact-match only in v0 (alias/domain rules out of scope — do not add).
2. Unknown sender → resolve to a `Reject` disposition (closed enum
   `{Accept, Reject, EscalateToHuman}`), NOT `Accept`. Fail-closed.
3. Normalization is deterministic and applied to BOTH stored + incoming addresses.

## Acceptance

- [ ] Unit: known address → `Principal(delegate_id, tenant_id, claims)`.
- [ ] Unit: unknown address → `Reject` (never `Accept`).
- [ ] Unit: normalization round-trips (`Foo <A@B.com>` and `a@b.com` resolve same).
