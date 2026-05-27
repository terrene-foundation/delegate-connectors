---
type: DISCOVERY
date: 2026-05-27
created_at: 2026-05-27T03:45:00Z
author: agent
session_id: email-connector-implement
session_turn: 2
project: email-connector
topic: DelegateIdentity *_ref fields are validated against ^[a-zA-Z0-9_-]+$ so they cannot carry an email address — authenticate() must resolve by delegate_id, not by an email on the identity
phase: implement
tags: [sdk-constraint, authenticate, principal-resolution, spec-amendment]
---

# DISCOVERY — DelegateIdentity refs reject email addresses

## Finding (kailash 2.26.2)

`specs/email-connector.md` says `authenticate(identity, envelope)` should
"resolve the sender/recipient email address in `identity` to a `Principal`."
But the shipped `DelegateIdentity` validates `sovereign_ref` /
`role_binding_ref` / `genesis_ref` against `^[a-zA-Z0-9_-]+$` (via
`kailash.trust._locking.validate_id`, `types.py:384`). An email address
(`alice@example.com`) contains `@` and `.` and is REJECTED at construction:

```
ValueError: DelegateIdentity.sovereign_ref rejected: Invalid identifier:
contains unsafe characters (must match ^[a-zA-Z0-9_-]+$)
```

So the email address CANNOT ride on any `DelegateIdentity` ref field. The
identity's stable dispatch key is its `delegate_id` (a `uuid.UUID`).

## Resolution (v0 convention, spec amendment)

- `EmailConnector.authenticate(identity, envelope)` resolves the identity by
  its **`delegate_id`** against the `EmailPrincipalResolver` (which is now
  dual-keyed: by normalized email AND by `delegate_id` string). Unknown
  delegate_id → fail-closed `ConnectorAuthenticationError` (the closed-enum
  `Reject` disposition) — the spec's unknown-sender contract is preserved.
- The **email address** is carried in the message payload (`invoke`'s
  `{sender, to, subject, body}`) and on `Principal` lookups via the
  email-keyed view — the transport/dispatch path is where the literal email
  lives, exactly where it belongs.

This keeps the spec's two hard contracts intact — (a) a known identity
resolves to a `Principal`, (b) an unknown one is `Reject`ed fail-closed — while
respecting the shipped identity's character constraint. The spec line "resolve
the email address in identity" is amended to "resolve the dispatch identity
(by delegate_id); the email lives on the payload + Principal claims."

## For Discussion

1. The conformance `BehaviouralOutcome` is keyed on dispatch outcome, not on
   how the principal was keyed. Does resolving by `delegate_id` vs email change
   any vector's `expected` outcome, or is the keying an implementation detail
   the behavioural contract is blind to?
2. Counterfactual: had `DelegateIdentity` permitted email-shaped refs, would
   binding the resolver to the email (not the UUID) have been more fragile —
   e.g. an address change re-rooting the dispatch identity? The UUID key is
   stable across address changes; is that strictly better for v0?
3. Should the email→delegate_id binding itself be an audited record (so a
   later session can prove which address mapped to which principal at dispatch
   time), or is the directory's static mapping sufficient for v0?
