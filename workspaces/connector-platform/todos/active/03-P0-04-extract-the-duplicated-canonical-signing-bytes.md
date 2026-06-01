# P0-04 — Extract the duplicated canonical signing-bytes helpers into ONE shared module (+ same-commit LOC/grep invariant test)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~150 LOC
> **Depends on:** none — Wave 1 (no deps)
> **Implements:** architecture §3.3; specs notes #1; specs/canonical-signing-bytes.md §1-§6 (FROZEN v1); rules/refactor-invariants.md MUST-1

## What (≤3 sentences)

Extract build_action_signing_bytes / build_read_signing_bytes / verify_action_envelope / verify_read_receipt — duplicated verbatim in all four connectors — into ONE shared host module the factory owns. These are conformance-frozen producers (specs §1-§6 frozen v1); the extraction must preserve byte-for-byte output. Land a same-commit grep/LOC invariant test so the parallel Wave-5 worktree merges cannot silently re-inline the extracted helpers undetected (refactor-invariants.md MUST-1).

## Deliverable

A new shared `delegate_connectors_host/signing_bytes.py` exporting the four signing-helper functions (canonical bytes unchanged), the four per-connector duplicate definitions removed and replaced by imports, AND a same-commit invariant test asserting zero residual helper definitions inside connectors/.

## Files touched

- delegate_connectors_host/signing_bytes.py (new shared module — moved helpers)
- connectors/email/src/delegate_connectors/email/connector.py:115-217 (remove duplicate defs, import from shared)
- connectors/slack/src/delegate_connectors/slack/connector.py (remove duplicate defs, import)
- connectors/telegram/src/delegate_connectors/telegram/connector.py (remove duplicate defs, import)
- connectors/whatsapp/src/delegate_connectors/whatsapp/connector.py + __init__.py (remove duplicate defs + re-export, import)
- tests/regression/test_signing_helper_loc_invariant.py (new — grep-count assertion)

## Invariants (MUST hold)

- canonical bytes are byte-identical before and after extraction (specs canonical-signing-bytes §1-§6 FROZEN v1 — CONFORM, never edit)
- all four connectors import the SAME shared helper (zero residual duplicate definitions)
- the helpers still call kailash.trust._json.canonical_json_dumps (no change to the canonicalization source)
- whatsapp's __init__.py re-export is repointed to the shared module
- a same-commit invariant test asserts zero residual build_action_signing_bytes/build_read_signing_bytes/verify_action_envelope/verify_read_receipt DEFINITIONS inside connectors/ (only imports) — guards against silent re-inline by the parallel Wave-5 worktree merges (refactor-invariants.md MUST-1)

## Value anchor

Architecture §3.3: the factory "absorbs the ~250-LOC compose ceremony every connector hand-copies". specs notes #1: de-duping the verbatim-duplicated helpers is the architecturally-correct direction and the natural home is the factory module — and the host-side-signing refactor ALREADY forces touching all four sign paths.

## Acceptance criteria

- [ ] all four signing helpers live in one shared module; the four duplicate definitions are deleted
- [ ] conformance vectors produce byte-identical canonical bytes before and after extraction (specs §1-§6 unchanged)
- [ ] all four connectors import the shared helpers; whatsapp __init__ re-export repointed
- [ ] a same-commit LOC/grep invariant test in the CI default path asserts zero residual helper definitions inside connectors/

## Test plan

Refactor-invariant test (refactor-invariants.md): run the existing conformance vector set (canonical-signing-bytes §6 vectors A-E + reject suite) against the shared helpers and assert byte-identical output to the pre-extraction connectors. Per-connector unit suites (test_connector) pass unchanged. Same-commit grep invariant: `grep -c` for helper DEFINITIONS inside connectors/ returns zero (only imports remain); this test lives in the CI default path (refactor-invariants.md MUST-2).
