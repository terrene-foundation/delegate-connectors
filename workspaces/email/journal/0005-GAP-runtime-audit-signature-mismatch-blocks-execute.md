---
type: GAP
date: 2026-05-27
created_at: 2026-05-27T03:25:00Z
author: agent
session_id: email-connector-implement
session_turn: 1
project: email-connector
topic: DelegateRuntime audit-emit signs payload-only bytes but AuditChainEngine verifies full-entry signing bytes — execute() always fails with a real Ed25519Verifier
phase: implement
tags:
  [sdk-bug, runtime, audit, ed25519, blocker, zero-tolerance-rule-4, repo-scope]
---

# GAP — DelegateRuntime audit emission cannot verify under a real Ed25519Verifier

## Finding (verified by introspection + executable probe, kailash 2.26.2)

`DelegateRuntime.execute(...)` (which is `async`, not sync) drives the TAOD
lifecycle and emits one audit event per phase transition. Each emission is
produced by `DelegateRuntime._emit_phase_audit` (`runtime.py:1709`):

```python
canonical_bytes = canonical_json_dumps(payload).encode("utf-8")   # payload ONLY
signature = self._signer(canonical_bytes)
self._audit_engine.emit_event(event_type=..., payload=payload,
                              signer_identity=self._identity, signature=signature)
```

But `AuditChainEngine.emit_event` (`audit.py:~850`) cryptographically verifies
that signature against **the full entry's signing bytes**, NOT the payload:

```python
if not self._verifier.verify(entry.to_signing_bytes(), sig_bytes, signer_id): ...
```

`AuditChainEntry.to_signing_bytes()` (`audit.py:376`) is the canonical JSON of
`to_signing_dict()` (`audit.py:349`):

```python
{"sequence", "previous_hash", "event_type", "event_payload",
 "signer_delegate_id", "signed_at"}   # six fields, payload is only ONE of them
```

The signer is invoked over `canonical_json_dumps(payload)` (one field's worth of
bytes); the verifier checks the signature over the six-field entry bytes. These
byte strings are never equal, so `verify(...)` returns `False`, and `emit_event`
raises `AuditChainSignatureError` on the FIRST phase transition (`thinking`).
`execute()` therefore returns `taod_state.phase == "failed"` with
`dispatch_result is None` for every input — it can never reach the ACTING phase
that invokes the connector.

The same mismatch exists on the `DispatchSurface.dispatch` path
(`dispatch.py:1951` signs `canonical_json_dumps(payload)`; `dispatch.py:2011`
verifies the signer output against `canonical_bytes` — which PASSES — then
`dispatch.py:2036` calls `emit_event`, which RE-verifies against
`to_signing_bytes()` — which FAILS). Two incompatible verification surfaces for
one signature.

## Executable proof

A throwaway probe composed the full runtime exactly per `specs/runtime-composition.md`
(real Ed25519 keypair, `PrincipalDirectory` with `verification_keys`,
`Ed25519Verifier`, `TenantScopedCascade` with a signed `register_root_grantee`
grant_proof, `Role`, `DispatchSurface`, `DelegateRuntime`). All constructors
succeeded; `isinstance(EmailConnector(...), Connector)` is True with zero
remaining abstractmethods. `await runtime.execute({...})` returned:

```
PHASE failed
reason: "audit emit failed at phase='thinking': AuditChainSignatureError"
```

A second probe proved the failure is NOT connector-side:

```
verify(entry.to_signing_bytes(), sign(canonical_json_dumps(payload))) -> False   # what the runtime does
verify(entry.to_signing_bytes(), sign(entry.to_signing_bytes()))      -> True    # the correct bytes
engine.emit_event(..., signature=sign(entry.to_signing_bytes()), signed_at=pinned) -> OK seq 0
```

The connector's OWN `read`/`write` (which sign the receipt's own
`canonical_bytes`) DO produce verifiable receipts — the bug is solely in the
runtime/dispatch audit-emit path's choice of signed bytes.

## Disposition

- **This is an SDK bug in `kailash.delegate` (kailash-py), NOT in connector code.**
  Per `zero-tolerance.md` Rule 4, the fix belongs in the SDK; per
  `repo-scope-discipline.md`, this repo (delegate-connectors) MUST NOT edit or
  file issues against kailash-py without explicit, journaled user authorization.
  No workaround (monkeypatching the runtime, swapping in a permissive verifier,
  or downgrading to `NullVerifier`) is acceptable: the spec mandates a real
  `Ed25519Verifier`, and `NullVerifier` rejects every signature too.
- **Buildable now (unaffected):** todos 01–05 (scaffold, SMTP, IMAP, directory,
  the `EmailConnector(Connector)` core), 07 (Tier-1 unit tests), and the
  connector-level SMTP→IMAP round-trip + `read`/`write` receipt-verification in 08. The connector subclasses `Connector` directly, satisfies the ABC, and its
  `read`/`write` emit NON-EMPTY receipts that verify under the real
  `Ed25519Verifier` (proven above).
- **Blocked by this bug:** todo 06's `runtime.execute(...)` end-to-end assertion
  and the `test_e2e.py` `RuntimeExecutionResult`-carries-verifiable-envelope
  assertion in todo 08. `compose.py` can still BUILD a valid `DelegateRuntime`
  (all constructors pass); only `execute()` cannot complete past the audit gate.

## Follow-up (needs user decision)

1. **Recommended:** file an SDK bug against kailash-py (the BUILD repo) —
   `_emit_phase_audit` + `DispatchSurface.dispatch` MUST sign
   `entry.to_signing_bytes()`, not `canonical_json_dumps(payload)`. This requires
   explicit cross-repo authorization per `repo-scope-discipline.md`. Surface a
   minimal repro scoped to the `kailash.delegate` API surface per
   `upstream-issue-hygiene.md`.
2. Ship the connector + connector-level Mailpit round-trip this cycle (real
   value, no mocks at the boundary). `compose.py` builds the runtime and
   documents the `execute()` blocker inline with this journal reference.

## For Discussion

1. The dispatch path verifies the signer output against `canonical_bytes`
   (`dispatch.py:2011`) AND then the engine re-verifies against
   `to_signing_bytes()` (`dispatch.py:2036`→`emit_event`). If the SDK authors
   intended the signer to sign the payload, why does `emit_event` verify the
   full entry — and if they intended the full entry, why does dispatch's own
   pre-check use `canonical_bytes`? Which surface is the contract?
2. If `_emit_phase_audit` had instead passed a signer that receives the entry's
   signing bytes (sequence/previous_hash known only inside the locked
   `emit_event` critical section), could the current `signer(canonical_bytes)`
   contract even express that — or does the fix require the engine to sign
   internally rather than accept a pre-computed signature?
3. Counterfactual: had the spec author composed and RUN a `DelegateRuntime`
   during `/analyze` (rather than introspecting signatures only), this blocker
   would have surfaced at analyze time and the shard plan would have scoped the
   runtime e2e as gated. What in the analyze protocol should require an
   executable composition probe for a runtime this intricate?
