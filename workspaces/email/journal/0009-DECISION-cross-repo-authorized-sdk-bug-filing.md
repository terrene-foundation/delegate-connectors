---
type: DECISION
date: 2026-05-27
created_at: 2026-05-27T00:00:00Z
author: human
session_id: email-connector-run
session_turn: 14
project: email
topic: cross-repo authorization to file the delegate audit-signature SDK bug
phase: redteam
tags: [cross-repo, upstream-issue, sdk-bug, authorization]
---

# DECISION — Cross-repo authorization: file the delegate audit-signature SDK bug

cross-repo-authorized: terrene-foundation/kailash-py

## Authorization (per repo-scope-discipline § User-Authorized Exception)

- **Requester:** user (jack@kailash.ai), this session.
- **Target repo:** terrene-foundation/kailash-py.
- **Bounded action:** ONE `gh issue create` reporting the `kailash.delegate`
  audit-signature contract defect (journal 0005). No other cross-repo action.
- **Verbatim instruction:** in answer to "Want me to draft + file that SDK bug?
  (yes / no)" the user replied: **"approved"**.
- **Timestamp:** 2026-05-27.
- **Confirmation gate:** the issue BODY is presented to the user for a final
  disclosure-scrub yes/no BEFORE `gh issue create` runs (upstream-issue-hygiene
  MUST-1 — "the user said yes once" is NOT standing approval for the body).

## The defect (root cause)

`DelegateRuntime._emit_phase_audit` (`runtime.py:1709-1710`) signs
`canonical_json_dumps(payload)`. `AuditChainEngine.emit_event` (`audit.py:852`)
verifies that signature against `AuditChainEntry.to_signing_bytes()` =
`canonical_json_dumps(to_signing_dict())`, where `to_signing_dict()` includes
`sequence`, `previous_hash`, `event_type`, `signer_delegate_id`, `signed_at` —
fields `emit_event` assigns AFTER receiving the signature. The two byte-strings
can never match → `AuditChainSignatureError` at the first audit-visible event.
The contract is structurally unsatisfiable by any caller.

Reproduced with ~25 lines of pure `kailash` API (no connector code) — raises
`AuditChainSignatureError` at sequence=0 under `Ed25519Verifier`.

## Consequence

Blocks `runtime.execute()` end-to-end for ANY connector under a real verifier —
the reason the email connector's runtime e2e is xfail (journal 0005). This is the
#1035 "Delegate runs end-to-end" acceptance blocker for the whole OSS substrate.

## Scrub

Issue body uses ONLY `kailash.*` public-API symbols + generic identifiers; NO
delegate-connectors / email / workspace / finding-tag context (upstream-issue-hygiene
MUST-2/3). Presented for final review before filing.

## For Discussion

1. The repro isolates the defect at `emit_event` rather than `runtime.execute()` —
   does the maintainer need the full runtime-level manifestation too, or is the
   `emit_event` contract-level repro the more actionable root-cause demonstration?
2. If the fix moves signing to AFTER `emit_event` assigns sequence/previous_hash
   (sign-the-built-entry), does that break the cross-SDK byte-parity the
   `to_signing_bytes()` docstring claims with the rs implementation?
3. Counterfactual: had we NOT verified the spine before building (task #2), this
   defect would have surfaced only at the email connector's e2e — would it then
   have looked like a connector bug rather than an SDK bug?
