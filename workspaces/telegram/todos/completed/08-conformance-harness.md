# Todo 08 — Conformance harness (reuse vendored canonical set)

**Implements:** `specs/conformance.md` (+ `specs/test-infrastructure.md` § Receipt agreement)
**Type:** Test (half-active; feedback-loop shard) · **Capacity:** single shard
**Depends:** 05, 07

## Do

- `connectors/telegram/tests/conformance/loader.py` — a `VendoredConformanceLoader`
  re-hydrating each record into typed `ConformanceVector` (proper `SpecAnchor` +
  `BehaviouralOutcome`) from the monorepo-shared vendored fixture
  `tests/fixtures/delegate-conformance/canonical.json`. REUSE the vendored fixture —
  do NOT re-source from kailash-py (per `specs/conformance.md` § Resolution A).
- `connectors/telegram/tests/conformance/test_canonical_set.py`
  (`@pytest.mark.conformance`), split in two halves mirroring email:
  - **Ships now (concrete, runs today):** fixture path resolves; set non-empty; every
    record is a `ConformanceVector`; shipped `validate_vector_set` accepts the set;
    ids unique; every `expected` ∈ closed enum `{Accept, Reject, EscalateToHuman}`;
    every vector has a `SpecAnchor`; the `TelegramConnector` composes against
    `DelegateRuntime` without raising (via `build_telegram_runtime` — todo 05).
  - **Gated on kailash-py#1182 (strict `xfail` per vector):** per-vector outcome
    assertion drives each vector's `given` through the composed runtime and asserts
    outcome == `expected`. Strict-`xfail` so it flips to XPASS and FAILS the suite by
    design when #1182 lands, forcing marker removal + per-vector scenario wiring.

## Acceptance

- [ ] `../../.venv/bin/python -m pytest connectors/telegram/tests/conformance -q` green —
      well-formedness + composition pass NOW; per-vector outcome tests `xfail`-strict.
- [ ] Loader reuses `tests/fixtures/delegate-conformance/canonical.json` (no re-sourcing
      from kailash-py).
- [ ] Every `expected` validated against the closed enum `{Accept, Reject, EscalateToHuman}`.
