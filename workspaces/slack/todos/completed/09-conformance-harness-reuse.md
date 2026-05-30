# Todo 09 — Conformance harness reuse + e2e strict-xfail

**Implements:** `specs/conformance.md` (+ `02-plans/02-connector-spec.md` § Responsibilities)
**Type:** Test · **Capacity:** single shard (3 invariants; mirrors email's conformance treatment)
**Depends:** 05, 06

## Do

- Reuse the monorepo-shared vendored canonical set at
  `tests/fixtures/delegate-conformance/canonical.json` (5 vectors: DV-3/5/7/9/10).
  Do NOT re-source from kailash-py — the fixture is already vendored at the
  monorepo root (`specs/conformance.md`; `workspaces/email/journal/0012`).
- `connectors/slack/tests/conformance/loader.py` — a `VendoredConformanceLoader`
  (mirror email's) that re-hydrates each record into typed `ConformanceVector`
  instances (proper `SpecAnchor` + `BehaviouralOutcome`), replacing the SDK's broken
  `ConformanceVectorLoader.load_canonical()`.
- `connectors/slack/tests/conformance/test_canonical_set.py`
  (`@pytest.mark.conformance`):
  - **Ships now (runs + passes):** the vendored set loads + hydrates; shipped
    `validate_vector_set` accepts it (well-formedness + id-uniqueness); every
    `expected` is in the closed enum `{Accept, Reject, EscalateToHuman}`; the
    `SlackConnector` composes against `DelegateRuntime` without raising.
  - **Strict-xfail (gated on kailash-py#1182):** the per-vector outcome assertion
    (drive each vector's `given` through `await runtime.execute()` and assert
    outcome == `expected`) AND the e2e `execute()` outcome — both strict-xfailed,
    mirroring email exactly. They flip to XPASS and force per-vector scenario wiring
    when #1182 lands.

## Invariants (3)

1. The vendored `canonical.json` loads + validates (well-formedness gate passes now).
2. The `SlackConnector` composes against `DelegateRuntime` without raising (ABC
   composition harness passes now).
3. Per-vector outcome + e2e `execute()` are strict-xfail (NOT skipped, NOT passed)
   — same treatment as email; no re-sourcing from kailash-py.

## Acceptance

- [ ] `../../.venv/bin/pytest connectors/slack/tests/conformance -q -m conformance`
      green — the now-active half passes; the gated half reports as strict-xfail
      (xfailed, not xpassed).
- [ ] The loader reads the monorepo-root `tests/fixtures/delegate-conformance/canonical.json`
      (no new fetch from kailash-py).
