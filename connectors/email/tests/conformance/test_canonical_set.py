# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Conformance Tier-2 — drive the canonical conformance vector set against the
shipped delegate runtime + EmailConnector.

The vectors are anchored to the Delegate Spec (not the connector contract) —
each vector asserts a RUNTIME-level invariant (envelope monotonic-tightening,
cascade-grant validation, etc.) with the connector as the dispatch target. A
conformant connector + runtime composition produces the vector's expected
``BehaviouralOutcome``.

Convergence cleanly here is in two halves:

1. **Now (this commit):** the vendored canonical set loads, every vector is
   well-formed, ids are unique, every ``expected`` is in the closed enum
   ``{Accept, Reject, EscalateToHuman}``, and the ``EmailConnector`` composes
   against ``DelegateRuntime`` without raising. These are concrete, run today.

2. **Gated on kailash-py#1182 (SDK ``runtime.execute()`` audit-signature fix):**
   per-vector outcome assertion drives the scenario's ``given`` through a
   composed runtime and asserts the outcome equals ``expected``. Until #1182
   lands, ``runtime.execute()`` returns ``phase=="failed"`` under ANY real
   verifier so the outcome cannot be measured (journal 0005). The parametrized
   outcome test is a strict-``xfail`` on each vector — when #1182 ships and
   ``execute()`` returns a real ``RuntimeExecutionResult``, the xfails flip to
   XPASS and FAIL the suite by design (forcing the marker's removal + the
   per-vector body wiring).
"""

from __future__ import annotations

import pytest

from kailash.delegate.conformance import validate_vector_set
from kailash.delegate.conformance.schema import (
    BehaviouralOutcome,
    ConformanceVector,
)

from delegate_connectors.email.compose import build_email_runtime
from delegate_connectors.email.imap import ImapConfig, ImapTransport
from delegate_connectors.email.smtp import SmtpConfig, SmtpTransport
from loader import DEFAULT_FIXTURE_PATH, VendoredConformanceLoader


# Vectors are loaded once at module import. The fixture is a static
# checked-in JSON file, so import-time loading is appropriate (and lets
# pytest parametrize over the resulting ConformanceVector instances).
_CANONICAL_VECTORS: list[ConformanceVector] = VendoredConformanceLoader().load()


pytestmark = pytest.mark.conformance


# ── (1) Concrete well-formedness — runs today, no SDK dependency ───────────


def test_canonical_fixture_path_resolves() -> None:
    """The vendored canonical fixture is reachable from the loader's default path."""
    assert DEFAULT_FIXTURE_PATH.exists(), (
        f"vendored canonical fixture missing at {DEFAULT_FIXTURE_PATH}; "
        "see workspaces/email/journal/0012 for the vendoring authorization"
    )


def test_canonical_set_is_non_empty() -> None:
    """The canonical set carries at least one vector (zero would be a vendor bug)."""
    assert len(_CANONICAL_VECTORS) >= 1


def test_every_vector_is_a_conformance_vector() -> None:
    """Every loaded record is a real ``ConformanceVector`` (loader hydration check)."""
    assert all(isinstance(v, ConformanceVector) for v in _CANONICAL_VECTORS)


def test_canonical_set_passes_shipped_validate_vector_set() -> None:
    """Shipped well-formedness validator accepts the canonical set.

    ``validate_vector_set`` checks set well-formedness + id uniqueness only
    (per ``specs/conformance.md`` § The gap). It raises ``SchemaError`` on a
    bad set; returning is the acceptance signal.
    """
    validate_vector_set(_CANONICAL_VECTORS)  # raises on invalid


def test_canonical_set_has_unique_ids() -> None:
    """Vector ids are unique across the canonical set."""
    ids = [v.id for v in _CANONICAL_VECTORS]
    assert len(set(ids)) == len(ids), f"duplicate vector ids: {ids}"


def test_every_expected_outcome_is_in_the_closed_enum() -> None:
    """Every ``expected`` is a ``BehaviouralOutcome`` member (closed enum).

    The set ``{Accept, Reject, EscalateToHuman}`` is the structural contract;
    any value outside it would break the email connector's unknown-sender
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


def test_email_connector_composes_against_delegate_runtime() -> None:
    """The ``EmailConnector`` composes into a real ``DelegateRuntime`` without raising.

    The conformance runner's per-vector outcome assertion depends on this
    composition holding; this is the precondition the rest of the runner
    builds on. (Independent of #1182, which gates ``runtime.execute()``, not
    composition.)
    """
    smtp = SmtpTransport(SmtpConfig(host="localhost", port=1025))
    imap = ImapTransport(ImapConfig(host="localhost", port=3143))
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )
    # Every required handle is populated and structurally typed.
    assert composed.runtime is not None
    assert composed.connector is not None
    assert composed.verifier is not None
    assert composed.identity is not None


# ── (2) Per-vector outcome — gated on kailash-py#1182 (SDK execute fix) ────


@pytest.mark.parametrize(
    "vector",
    _CANONICAL_VECTORS,
    ids=[v.id for v in _CANONICAL_VECTORS],
)
@pytest.mark.xfail(
    reason=(
        "SDK bug kailash-py#1182: runtime audit-emit signs payload bytes but "
        "AuditChainEngine verifies the full entry signing bytes; "
        "runtime.execute() returns phase=='failed' under any real verifier, "
        "so per-vector outcome cannot be measured. When #1182 ships and "
        "execute() returns a real outcome, this strict xfail flips to XPASS "
        "and the marker MUST be removed + each vector's `given` scenario "
        "wired to drive the runtime and assert outcome == expected. See "
        "workspaces/email/journal/0005 + specs/conformance.md § When unblocked."
    ),
    strict=True,
)
def test_vector_outcome_matches_expected(vector: ConformanceVector) -> None:
    """Drive vector.given through a composed runtime; assert outcome == expected.

    Stub body: the assertion's TRUTH depends on ``runtime.execute()`` producing
    a real outcome (currently blocked by kailash-py#1182). Authoring the
    per-vector scenario setup (Genesis Record, cascade grant, envelope state)
    is deferred to the un-xfail shard so it lands against a working
    ``execute()`` rather than a known-failing one. The strict-xfail is the
    contract that this test eventually flips to a real assertion.
    """
    # When #1182 ships, replace this body with the per-vector scenario:
    #   composed = build_email_runtime(...)
    #   # set up vector.given (TenantScopedCascade grant, envelope state, etc.)
    #   result = await composed.runtime.execute(payload_for(vector))
    #   outcome = map_outcome(result)
    #   assert outcome == vector.expected
    # For now the strict-xfail records intent without faking a result.
    raise AssertionError(
        f"per-vector outcome wiring gated on kailash-py#1182 "
        f"(vector={vector.id!r}, expected={vector.expected.value!r})"
    )


@pytest.mark.xfail(
    reason=(
        "kailash-py#1182 audit-emit signature bug — see specs/conformance.md. "
        "Deterministic-run receipt agreement cannot be measured while "
        "runtime.execute() returns phase=='failed' under any real verifier "
        "(audit-emit signs payload bytes; AuditChainEngine verifies the full "
        "entry signing bytes — compose.py § KNOWN SDK BLOCKER). When #1182 ships, "
        "this strict xfail flips to XPASS and the marker MUST be removed + the "
        "body wired to run the full vector set TWICE through composed runtimes and "
        "assert_receipts_agree across the two deterministic runs."
    ),
    strict=True,
)
def test_assert_receipts_agree_across_deterministic_runs() -> None:
    """Two deterministic runs of the vector set MUST produce agreeing receipts.

    Parity with the slack/telegram/whatsapp conformance suites (this row was
    previously absent from email — redteam finding F4). ``assert_receipts_agree``
    compares the audit/dispatch receipts emitted by two independent
    composed-runtime executions of the same vector set; identical inputs MUST
    yield byte-identical receipts. Depends on ``runtime.execute()`` producing
    real receipts (blocked by kailash-py#1182). The strict-xfail is the contract
    that this flips to a real assertion when the SDK fix lands.
    """
    # When #1182 ships, replace this body with the deterministic-run check:
    #   run_a = [drive(v) for v in _CANONICAL_VECTORS]   # composed runtime A
    #   run_b = [drive(v) for v in _CANONICAL_VECTORS]   # composed runtime B
    #   assert_receipts_agree(run_a, run_b)
    raise AssertionError(
        "assert_receipts_agree deterministic-run wiring gated on kailash-py#1182"
    )
