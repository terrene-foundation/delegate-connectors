# Todo 11 — Conformance harness (vendored canonical set)

**Implements:** `specs/conformance.md` (+ `02-plans/02-connector-spec.md` § Unknown-sender disposition — the closed `{Accept, Reject, EscalateToHuman}` enum)
**Type:** Test · **Capacity:** single shard (mostly test code)
**Depends:** 07, 08

**Value-anchor:** delivers the brief acceptance criterion "conformance harness reuses the monorepo-shared canonical set" — mirroring email's half-active treatment so WhatsApp conforms to the same canonical vectors.

## Do

- Reuse the vendored monorepo-root fixture `tests/fixtures/delegate-conformance/canonical.json`
  (5 vectors: DV-3/5/7/9/10 — 4 Reject + 1 Accept). Do NOT re-vendor or fork it.
- `connectors/whatsapp/tests/conformance/loader.py` — `VendoredConformanceLoader` re-hydrating
  each record into typed `ConformanceVector` (proper `SpecAnchor` + `BehaviouralOutcome`),
  mirroring email's loader (replaces the SDK's broken `load_canonical()`).
- `connectors/whatsapp/tests/conformance/test_canonical_set.py` (`@pytest.mark.conformance`):
  - **Ships + passes now:** fixture loads + hydrates; shipped `validate_vector_set` accepts the
    set (well-formedness + id uniqueness); every `expected` is in the closed enum; the
    `WhatsAppConnector` composes against `DelegateRuntime` without raising.
  - **Strict-xfail (gated on kailash-py#1182):** per-vector outcome assertion — drive each
    vector's `given` through the composed runtime and assert outcome == `expected`; plus the
    `assert_receipts_agree` deterministic-run row. When #1182 lands these flip to XPASS and
    force per-vector scenario wiring + marker removal.

## Acceptance

- [ ] `../../.venv/bin/pytest connectors/whatsapp/tests/conformance -q` green: the
      well-formedness + composition rows pass; the per-vector outcome rows are strict-xfail.
- [ ] The loader reads the shared root fixture (no per-connector copy of `canonical.json`).
- [ ] Per-vector outcome + `assert_receipts_agree` rows are marked strict-xfail with a comment
      citing kailash-py#1182.
