# P0-06 — Build the opaque non-introspectable BoundTransport handle type (closure-captured credential; no __dict__/__getstate__ escape)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~140 LOC
> **Depends on:** none — Wave 1 (no deps)
> **Implements:** architecture §3.5 layer 2; architecture §2; specs bound_transport_requirements

## What (≤3 sentences)

Build the NEW BoundTransport handle type (does not exist today, zero hits). It exposes ONLY send(...)/fetch(...), has NO .config accessor or any attribute returning the underlying config/password/token, a credential-redacting __repr__, and is NOT serializable. CRITICAL hardening per security MEDIUM finding: the wrapped credential-bearing transport MUST be closure-captured (or name-mangled __slots__ holding only a brokered callable), NOT a plain instance attribute — so it is unreachable via handle.__dict__, vars(handle), __getstate__/__reduce_ex__, or gc.get_referents walking. The current SmtpTransport/ImapTransport leak the secret via public .config.

## Deliverable

A new `delegate_connectors_host/bound_transport.py` exporting BoundTransport: a handle wrapping a brokered side-effect surface via closure capture (credential is NOT an instance attribute), exposing only send()/fetch(), with credential-redacting repr and all serialization paths (__reduce__, __reduce_ex__, __getstate__) disabled.

## Files touched

- delegate_connectors_host/bound_transport.py (new — BoundTransport handle type)

## Invariants (MUST hold)

- exposes ONLY send(...)/fetch(...) — no transport-config accessor, no credential getter
- NO .config accessor and no equivalent attribute/property returning SmtpConfig/ImapConfig/password/token (the named §3.5 leak)
- the wrapped credential-bearing transport is closure-captured or held in a name-mangled __slots__ holding only a brokered callable — NOT a plain instance attribute, so handle.__dict__ / vars(handle) / gc.get_referents(handle) expose no credential (security MEDIUM finding)
- credential-redacting __repr__ (repr MUST NOT print the secret)
- NOT picklable: __reduce__ AND __reduce_ex__ AND __getstate__ all raise (no serialization escape that dumps the bound credential)
- credential-blind by construction from the connector's view — the connector receives the handle, never the raw secret

## Value anchor

Architecture §3.5 layer 2 + §2: until this handle exists, "credential-blind" is FALSE and MUST NOT be marketed. The current transports recreate the n8n getCredentials() leak via public .config. BoundTransport is the structural enforcement that makes credential-blindness true. Brief success criterion: "it cannot see credentials it wasn't granted".

## Acceptance criteria

- [ ] BoundTransport exposes only send()/fetch() with no config or credential accessor
- [ ] repr is credential-redacting; pickling AND __getstate__ AND __reduce_ex__ all raise
- [ ] the credential is closure-captured (not an instance attribute) — unreachable via __dict__, vars(), or gc-referent walking
- [ ] a connector holding the handle cannot reach the underlying SmtpConfig/ImapConfig/password/token by any attribute, serialization, or referent path

## Test plan

Unit (the sub-invariants): assert hasattr send/fetch; assert NO .config/.password/.token/credential accessor (getattr raises / absent); assert repr(handle) contains no secret substring (redacted); assert pickle.dumps(handle) raises; assert handle.__dict__ contains no credential-bearing value (closure capture); assert __getstate__/__reduce_ex__ raise. Introspection sweep: dir(handle) + vars(handle) + gc.get_referents(handle) expose no credential-bearing name. BUILD half of the credential-blindness invariant TEST in P0-13.
