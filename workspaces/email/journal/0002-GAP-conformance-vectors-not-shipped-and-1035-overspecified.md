# GAP — Conformance vectors not shipped; #1035 acceptance over-specified

**Date:** 2026-05-27
**Phase:** /analyze
**Evidence:** `01-analysis/01-conformance-contract.md` + `03-runtime-infra-topology.md`.

## Gap 1 — Canonical conformance vectors are NOT in the wheel

`ConformanceVectorLoader.load_canonical()` raises `FileNotFoundError`. The canonical
set (`tests/fixtures/delegate-conformance/canonical.json`) lives only in the
kailash-py SOURCE tree, not the distributed package. Additionally, `validate_vector_set()`
only checks set well-formedness — there is NO connector-vs-vector execution harness
in the package; it must be authored here.

**Consequence:** the brief/#1035 acceptance criterion "pass the canonical conformance
vectors" is not runnable from the installed package. Sourcing the fixture requires
reading the kailash-py repo — a CROSS-REPO read, BLOCKED without explicit user
authorization per `repo-scope-discipline.md`. This is the one hard external/cross-repo
dependency in the workstream.

## Gap 2 — #1035 acceptance ↔ shipped API mismatch

#1035 acceptance: "Delegate runs end-to-end vs a real PACT engine + real Postgres
audit (NO mocks)." Unsatisfiable as written — the shipped runtime uses in-memory
`AuditChainEngine` + `Verifier`, with no PACT/Postgres hooks. The buildable path is
the shipped-API reality (in-memory audit, `Ed25519Verifier`, Mailpit). #1035's PACT
/Postgres line is aspirational (docstring-level only).

## Disposition (pending user decision — see session recommendation)

- Build connector + runtime + Mailpit real-infra tests now (fully determined, no gap).
- Conformance: recommend DEFER to a later shard (option B); vendoring vectors from
  kailash-py (option A) needs explicit cross-repo authorization.
- #1035 reconcile: build to shipped-API reality; treat PACT/Postgres line as
  aspirational. Confirm with user.
