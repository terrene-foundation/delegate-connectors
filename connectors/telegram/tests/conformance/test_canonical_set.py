# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Conformance Tier-2 — drive the canonical conformance vector set against the
shipped delegate runtime + TelegramConnector.

The vectors are anchored to the Delegate Spec (not the connector contract) —
each vector asserts a RUNTIME-level invariant (envelope monotonic-tightening,
cascade-grant validation, etc.) with the connector as the dispatch target. A
conformant connector + runtime composition produces the vector's expected
``BehaviouralOutcome``.

This is a near-exact mirror of the WhatsApp / email connector conformance
harness; it REUSES the monorepo-shared canonical set at
``tests/fixtures/delegate-conformance/canonical.json`` (no per-connector copy).

Convergence here is in two halves:

1. **Well-formedness:** the vendored canonical set loads, every vector is
   well-formed, ids are unique, every ``expected`` is in the closed enum
   ``{Accept, Reject, EscalateToHuman}``, every vector cites a ``SpecAnchor``,
   and the ``TelegramConnector`` composes against ``DelegateRuntime`` (via
   ``build_telegram_runtime``) without raising.

2. **Per-vector outcome (ACTIVE on kailash >= 2.28.0):** the per-vector driver
   (``vector_driver.drive_vector``) materializes each scenario's ``given``
   against the shipped ``kailash.delegate`` spine and asserts the observed
   ``BehaviouralOutcome`` equals ``expected``; plus an ``assert_receipts_agree``
   deterministic-run row. This was strict-xfail-gated on kailash-py#1182 (the
   runtime audit-emit path signed event PAYLOAD bytes while
   ``AuditChainEngine.emit_event`` verified the FULL entry signing bytes, so
   ``execute()`` returned ``phase=="failed"`` under any real verifier). Fixed at
   <= 2.28.1 (``workspaces/whatsapp/journal/0008``); the markers are removed and
   the per-vector driver drives the real assertions. The driver's vectors are
   connector-agnostic (they exercise the delegate spine); the
   ``TelegramConnector`` is the dispatch target via ``_make_composed``.
"""

from __future__ import annotations

import pytest

from kailash.delegate import assert_receipts_agree
from kailash.delegate.conformance import validate_vector_set
from kailash.delegate.conformance.schema import (
    BehaviouralOutcome,
    ConformanceVector,
)

from delegate_connectors.telegram.compose import build_telegram_runtime
from delegate_connectors.telegram.transport import TelegramConfig, TelegramTransport

from loader import DEFAULT_FIXTURE_PATH, VendoredConformanceLoader
from vector_driver import drive_two_deterministic_runs, drive_vector

# Vectors are loaded once at module import. The fixture is a static checked-in
# JSON file, so import-time loading is appropriate (and lets pytest parametrize
# over the resulting ConformanceVector instances).
_CANONICAL_VECTORS: list[ConformanceVector] = VendoredConformanceLoader().load()


pytestmark = pytest.mark.conformance


# ── (1) Concrete well-formedness — runs today, no SDK dependency ───────────


def test_canonical_fixture_path_resolves() -> None:
    """The shared canonical fixture is reachable from the loader's default path."""
    assert DEFAULT_FIXTURE_PATH.exists(), (
        f"shared canonical fixture missing at {DEFAULT_FIXTURE_PATH}; "
        "the Telegram harness reuses the monorepo-shared copy at "
        "tests/fixtures/delegate-conformance/canonical.json (no per-connector copy)"
    )


def test_canonical_set_is_non_empty() -> None:
    """The canonical set carries at least one vector (zero would be a vendor bug)."""
    assert len(_CANONICAL_VECTORS) >= 1


def test_every_vector_is_a_conformance_vector() -> None:
    """Every loaded record is a real ``ConformanceVector`` (loader hydration check)."""
    assert all(isinstance(v, ConformanceVector) for v in _CANONICAL_VECTORS)


def test_canonical_set_passes_shipped_validate_vector_set() -> None:
    """Shipped well-formedness validator accepts the canonical set.

    ``validate_vector_set`` checks set well-formedness + id uniqueness only. It
    raises on a bad set; returning is the acceptance signal.
    """
    validate_vector_set(_CANONICAL_VECTORS)  # raises on invalid


def test_canonical_set_has_unique_ids() -> None:
    """Vector ids are unique across the canonical set."""
    ids = [v.id for v in _CANONICAL_VECTORS]
    assert len(set(ids)) == len(ids), f"duplicate vector ids: {ids}"


def test_every_expected_outcome_is_in_the_closed_enum() -> None:
    """Every ``expected`` is a ``BehaviouralOutcome`` member (closed enum).

    The set ``{Accept, Reject, EscalateToHuman}`` is the structural contract;
    any value outside it would break the Telegram connector's unknown-sender
    disposition mapping.
    """
    valid = set(BehaviouralOutcome)
    for v in _CANONICAL_VECTORS:
        assert (
            v.expected in valid
        ), f"vector {v.id!r} has out-of-enum expected={v.expected!r}"


def test_every_vector_has_a_spec_anchor() -> None:
    """Every vector cites a ``SpecAnchor`` (mandatory per the schema)."""
    for v in _CANONICAL_VECTORS:
        assert v.spec_anchor is not None
        assert v.spec_anchor.section, f"vector {v.id!r} has empty spec_anchor"


def test_telegram_connector_composes_against_delegate_runtime() -> None:
    """The ``TelegramConnector`` composes into a real ``DelegateRuntime`` without raising.

    The conformance runner's per-vector outcome assertion depends on this
    composition holding; this is the precondition the rest of the runner builds
    on. (Independent of #1182, which gates ``runtime.execute()``, not
    composition.) Credentials come from the package autouse ``_telegram_test_env``
    fixture (env-only).
    """
    transport = TelegramTransport(TelegramConfig.from_env())
    composed = build_telegram_runtime(
        transport=transport,
        sender_user_id=424242,
        sender_chat_id=555000,
    )
    # Every required handle is populated and structurally typed.
    assert composed.runtime is not None
    assert composed.connector is not None
    assert composed.verifier is not None
    assert composed.identity is not None


# ── (2) Per-vector outcome — ACTIVE on kailash >= 2.28.0 ───────────────────


def _make_composed():
    """Fresh composed Telegram runtime for the per-vector driver.

    Each call builds an independent ``ComposedTelegramRuntime``; the driver needs
    fresh runtimes (DV-7 is single-shot, DV-9 needs a freshly-run audit engine,
    the determinism rows need two independent runs). Credentials come from the
    package autouse ``_telegram_test_env`` fixture (env-only). No live Telegram
    API call is asserted — the driver exercises the delegate spine; a dispatch
    that reaches the real API simply terminates the run, which the §7/§9 vectors
    handle identically (the determinism rows agree on a deterministic outcome).
    """
    transport = TelegramTransport(TelegramConfig.from_env())
    return build_telegram_runtime(
        transport=transport,
        sender_user_id=424242,
        sender_chat_id=555000,
    )


@pytest.mark.parametrize(
    "vector",
    _CANONICAL_VECTORS,
    ids=[v.id for v in _CANONICAL_VECTORS],
)
async def test_vector_outcome_matches_expected(vector: ConformanceVector) -> None:
    """Drive ``vector.given`` through the shipped spine; assert outcome == expected.

    The per-vector driver materializes each scenario (DV-3 widening cascade grant,
    DV-5 widening delegation envelope, DV-7 second-execute on a terminal runtime,
    DV-9 audit-chain round-trip, DV-10 sovereign-vs-service-account impersonation)
    against ``kailash.delegate`` primitives and returns the observed
    ``BehaviouralOutcome``. A conformant connector + runtime composition produces
    the vector's ``expected`` outcome.
    """
    observed = await drive_vector(vector, _make_composed)
    assert observed == vector.expected, (
        f"vector {vector.id!r}: observed {observed.value!r} != expected "
        f"{vector.expected.value!r}"
    )


async def test_assert_receipts_agree_across_deterministic_runs() -> None:
    """Two deterministic runs on identical input MUST produce agreeing receipts.

    ``assert_receipts_agree`` deep-compares the two ``RuntimeExecutionResult``
    receipt trees minus the per-run-by-design fields (``run_id`` + the
    per-transition ``at`` timestamp, plus ``dispatch_id`` / ``audit_head_hash`` /
    ``audit_chain_entries`` which incorporate the fresh dispatch UUID and per-run
    audit state) — the SAME ``exclude_fields`` as the Tier-2 e2e determinism test.
    Identical inputs yield agreeing receipts; divergence raises
    ``ReceiptsAgreementError`` and fails the row.
    """
    receipt_a, receipt_b = await drive_two_deterministic_runs(_make_composed)
    assert_receipts_agree(
        receipt_a,
        receipt_b,
        exclude_fields=frozenset(
            {
                "run_id",
                "at",
                "dispatch_id",
                "audit_head_hash",
                "audit_chain_entries",
            }
        ),
    )
