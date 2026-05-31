# Spec — Conformance (ACTIVE)

> **STATUS: ACTIVE (per-vector outcome assertions live 2026-05-31).** The
> vendored canonical fixture lives at
> `tests/fixtures/delegate-conformance/canonical.json` (monorepo root) and a
> local loader replaces the SDK's broken `ConformanceVectorLoader.load_canonical()`.
> Both halves now run as the `conformance` test marker across all four
> connectors (slack, telegram, whatsapp, email): (1) fixture load,
> well-formedness gate, ABC composition harness, AND (2) the per-vector outcome
> assertion — a connector-agnostic driver (`vector_driver.drive_vector`)
> materializes each vector's `given` against the shipped `kailash.delegate`
> spine and asserts the observed `BehaviouralOutcome == expected`, plus an
> `assert_receipts_agree` deterministic-run row.
>
> The per-vector half was previously **GATED on kailash-py#1182** (the runtime
> audit-emit path signed event PAYLOAD bytes while `AuditChainEngine.emit_event`
> verified the FULL entry signing bytes, so `runtime.execute()` returned
> `phase=="failed"` under any real verifier — journal/0005). **#1182 is fixed
> at <= 2.28.1** (`workspaces/whatsapp/journal/0008`); the strict-xfail markers
> are removed and the per-vector driver drives the real assertions.
>
> Historical receipts: original deferral `journal/0003`; un-deferral (Option A
> vendoring) `journal/0012`; #1182-fixed scope correction
> `workspaces/whatsapp/journal/0008`; Class E shard plan
> `workspaces/whatsapp/02-plans/03-f2-shard-plan.md`.

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

## What runs (both halves ACTIVE)

**Well-formedness (no SDK execute dependency):**

- Vendored canonical set loads and hydrates into typed `ConformanceVector` instances.
- Shipped `validate_vector_set` accepts the set (well-formedness + id uniqueness).
- Every `expected` is in the closed enum `{Accept, Reject, EscalateToHuman}`.
- Each connector composes against `DelegateRuntime` without raising.

**Per-vector outcome (ACTIVE on kailash >= 2.28.0):**

- `vector_driver.drive_vector(vector, make_composed)` materializes each vector's
  `given` against the shipped `kailash.delegate` primitives and returns the
  observed `BehaviouralOutcome`; the test asserts `observed == expected`.
- `vector_driver.drive_two_deterministic_runs(make_composed)` returns two
  independent `RuntimeExecutionResult` receipt trees; the test asserts
  `assert_receipts_agree` with `exclude_fields = {run_id, at, dispatch_id,
audit_head_hash, audit_chain_entries}` (the same set as the Tier-2 e2e
  determinism test).

The driver is **connector-agnostic** — the vectors exercise the delegate spine,
not connector code; the driver is copied per-connector (mirroring `loader.py`),
and only the `make_composed` thunk differs.

## Per-vector materialization (primitive → outcome map)

| Vector    | §   | Expected | Materialization (shipped `kailash.delegate` primitive)                                                                                                                      |
| --------- | --- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DV-3-001  | 3   | Reject   | `TenantScopedCascade.cascade_child` with a child envelope widening the parent's Financial dim → `EnvelopeWideningError` (Step 3 F5 tightening).                             |
| DV-5-001  | 5   | Reject   | `DelegateConstraintEnvelope.tighten_with` a wider Financial dim → `EnvelopeWideningError`.                                                                                  |
| DV-7-001  | 7   | Reject   | second `runtime.execute()` on a terminal runtime → `RuntimePhaseError` (single-shot TAOD phase monotonicity).                                                               |
| DV-9-001  | 9   | Accept   | `AuditChainEngine` head hash; replay reconstructed from each entry's `to_canonical_dict()` recomputes the SAME head hash.                                                   |
| DV-10-001 | 10  | Reject   | a `principal_kind="sovereign"` identity bound to a service-account-only connector role → `DispatchEnvelopeViolationError` (§10 G1 sovereign-vs-service-account separation). |

Reject is observed when the path raises one of the spine's documented violation
errors (`EnvelopeWideningError`, `CascadeScopeExpansionError`,
`CascadeTenantViolationError`, `DispatchCascadeViolationError`,
`DispatchEnvelopeViolationError`, `R2CompositionError`, `RuntimePhaseError`,
`RuntimeCompositionError`, `RuntimePostureBlockedError`) OR `runtime.execute()`
returns `phase == "failed"`.

## Un-xfailed (history)

The per-vector half was strict-xfail-gated on kailash-py#1182. #1182 is fixed at
<= 2.28.1 (`workspaces/whatsapp/journal/0008`); the markers were removed and the
per-vector driver wired across all four connectors (F2 Class E, 2026-05-31):
`test_vector_outcome_matches_expected` (5 vectors) +
`test_assert_receipts_agree_across_deterministic_runs`, 8 markers removed
(2 per connector × 4). DV-7/DV-9 against transports with no live Accept-path
(telegram real-API, whatsapp closed service window, email absent SMTP server)
still produce the correct outcome: DV-7 Rejects on the terminal-runtime second
execute, DV-9 Accepts via the pre-dispatch audit entries, and the determinism
rows agree because both runs terminate identically. The connector Accept-path
e2e (socket double / Mailpit) is a separate Tier-2 surface.
