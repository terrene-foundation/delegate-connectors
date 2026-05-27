# Spec — Conformance (GATED)

> **STATUS: DEFERRED (user-confirmed 2026-05-27, `journal/0003`).** Conformance is a
> follow-up shard — HIGH value (carries the value-anchor in `journal/0003`), deferred
> only because the vectors are unreachable without cross-repo access to kailash-py.
> The connector ships built + Mailpit-tested this cycle WITHOUT conformance. Re-pickup
> MUST re-validate the value-anchor + confirm cross-repo authorization. See
> `workspaces/email/01-analysis/00-synthesis.md` BLOCKER-1.

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

## Resolution options (user decision — see session recommendation)

- **(A) Vendor** the canonical fixture from kailash-py → `tests/fixtures/...`.
  Requires reading kailash-py — a CROSS-REPO read, BLOCKED without explicit user
  authorization per `repo-scope-discipline.md`.
- **(B) Defer** conformance to a later shard; build + Mailpit-test the connector
  now (delivers value independent of the vectors). Recommended.
- **(C) Author** vectors here from the Delegate Spec v0 (also cross-repo — the spec
  lives outside this repo).

## When unblocked

Build a `tests/conformance/runner.py` that loads vectors, drives each through a
composed `DelegateRuntime`, maps the result to `{Accept, Reject, EscalateToHuman}`,
asserts == `expected`, and runs `assert_receipts_agree` for determinism.
