# Spec — Conformance (PARTIALLY ACTIVE)

> **STATUS: HALF-ACTIVE (un-deferred 2026-05-27 under cross-repo authz at
> `workspaces/email/journal/0012`).** The vendored canonical fixture lives at
> `tests/fixtures/delegate-conformance/canonical.json` (monorepo root) and a
> local loader replaces the SDK's broken `ConformanceVectorLoader.load_canonical()`.
> The half that is **ACTIVE now**: fixture load, well-formedness gate, ABC
> composition harness — runs as the `conformance` test marker. The half that
> remains **GATED on kailash-py#1182**: per-vector outcome assertion (drives
> each vector's `given` through `runtime.execute()` whose audit-signature bug
> blocks any real verifier — journal/0005). The per-vector tests are
> strict-xfailed; when #1182 ships they flip to XPASS and force the marker's
> removal + per-vector scenario wiring.
>
> Original deferral receipt: `journal/0003`. Un-deferral receipt: `journal/0012`.

## Vector contract (verified)

`ConformanceVector` (frozen dataclass, `kailash/delegate/conformance/schema.py`):

- `id` — unique vector id.
- `spec_anchor` — mandatory dotted-decimal spec § reference (`SpecAnchor`).
- `given` — scenario preconditions.
- `behaviour` — the action exercised.
- `expected` — a **closed enum** `BehaviouralOutcome ∈ {Accept, Reject, EscalateToHuman}`.

The schema is **behavioural-only** — it asserts the dispatch OUTCOME, structurally
cannot assert engine internals.

## The gap (two parts)

1. **Fixture not shipped.** `ConformanceVectorLoader.load_canonical()` raises
   `FileNotFoundError` — the canonical set
   (`tests/fixtures/delegate-conformance/canonical.json`) lives only in the
   kailash-py SOURCE repo, not the PyPI wheel.
2. **No runner ships.** `validate_vector_set(vectors)` validates set
   well-formedness + id-uniqueness only. There is NO connector-vs-vector execution
   harness in the package — it must be authored here (drive each vector's `given`
   through a `DelegateRuntime.execute()` and assert the resulting outcome ==
   `expected`).

## Resolution chosen — Option A (vendor)

Option A landed 2026-05-27 under cross-repo authz `journal/0012`. The canonical
JSON is byte-for-byte from `terrene-foundation/kailash-py:tests/fixtures/delegate-conformance/canonical.json`
at ref `main` (5 vectors: DV-3/5/7/9/10, 4 Reject + 1 Accept).

- Vendored fixture: `tests/fixtures/delegate-conformance/canonical.json` (monorepo root, shared across connectors).
- Replacement loader: `connectors/email/tests/conformance/loader.py` (`VendoredConformanceLoader`) — re-hydrates each record with proper `SpecAnchor` + `BehaviouralOutcome` types.
- Harness: `connectors/email/tests/conformance/test_canonical_set.py` (`@pytest.mark.conformance`).

Option B (defer) is now closed. Option C (author from spec) is not pursued — the canonical set is authoritative.

## What ships now vs gated on kailash-py#1182

**Ships now (concrete, runs today):**

- Vendored canonical set loads and hydrates into typed `ConformanceVector` instances.
- Shipped `validate_vector_set` accepts the set (well-formedness + id uniqueness).
- Every `expected` is in the closed enum `{Accept, Reject, EscalateToHuman}`.
- The `EmailConnector` composes against `DelegateRuntime` without raising.

**Gated on kailash-py#1182 (strict xfail per vector):**

- Per-vector outcome assertion — drive each vector's `given` scenario through
  the composed runtime and assert outcome == `expected`. Blocked because the
  shipped audit-emit signs payload bytes while `AuditChainEngine` verifies the
  full entry signing bytes, so `runtime.execute()` returns `phase=="failed"` on
  any real verifier (journal/0005). When #1182 lands the strict xfails flip to
  XPASS and force the marker's removal + per-vector scenario wiring.
- Cross-impl receipt determinism via `assert_receipts_agree` — same dependency.

## When #1182 lands — un-xfail checklist

1. For each vector (DV-3-001, DV-5-001, DV-7-001, DV-9-001, DV-10-001), author
   the per-vector scenario setup that materializes the `given` clause:
   - DV-3-001 §3 (Reject) — Genesis Record + cascade grant widening Financial dim.
   - DV-5-001 §5 (Reject) — composition-level invariant on §5 of the Delegate Spec.
   - DV-7-001 §7 (Reject) — composition-level invariant on §7.
   - DV-9-001 §9 (Accept) — the single Accept case; well-formed composition.
   - DV-10-001 §10 (Reject) — composition-level invariant on §10.
2. Remove the strict-`xfail` marker on `test_vector_outcome_matches_expected`.
3. Replace the stub body with the per-vector driver: compose a runtime, materialize the `given`, await `runtime.execute()`, map the result to `BehaviouralOutcome`, assert `==` expected.
4. Add `assert_receipts_agree` deterministic-run assertion.
