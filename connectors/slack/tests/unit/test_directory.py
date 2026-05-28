# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for principal resolution + unknown-sender disposition.

Pure-Python: no Slack Web API client, no I/O. Covers dual-keyed resolution
(delegate_id primary, slack_id secondary), fail-closed Reject, case-significant
normalization, and team/workspace id carried in Principal.claims.
"""

from __future__ import annotations

import pytest

from kailash.delegate.dispatch import Principal

from delegate_connectors.slack.directory import (
    ResolutionOutcome,
    SlackPrincipalResolver,
    UnknownSenderDisposition,
)


def _principal(
    delegate_id: str = "d-alice",
    *,
    tenant_id: str = "t1",
    team_id: str | None = None,
) -> Principal:
    claims: dict[str, object] = {}
    if team_id is not None:
        claims["team_id"] = team_id
    return Principal(delegate_id=delegate_id, tenant_id=tenant_id, claims=claims)


# --- PRIMARY path: resolve_delegate_id -------------------------------------


def test_known_delegate_id_resolves_to_principal_with_accept():
    p = _principal("d-alice", tenant_id="t1", team_id="T0AAA1111")
    resolver = SlackPrincipalResolver({"U07ABCDE123": p})
    outcome = resolver.resolve_delegate_id("d-alice")
    assert outcome.accepted
    assert outcome.principal is p
    assert outcome.disposition is UnknownSenderDisposition.ACCEPT
    # The principal carries delegate_id, tenant_id, claims.
    assert outcome.principal.delegate_id == "d-alice"
    assert outcome.principal.tenant_id == "t1"


def test_unknown_delegate_id_resolves_to_reject_never_accept():
    resolver = SlackPrincipalResolver({"U07ABCDE123": _principal("d-alice")})
    outcome = resolver.resolve_delegate_id("d-unknown")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT
    assert outcome.disposition is not UnknownSenderDisposition.ACCEPT
    assert not outcome.accepted


# --- SECONDARY path: resolve_slack_id (payload attribution) ----------------


def test_slack_id_resolves_via_secondary_index_case_preserved():
    p = _principal("d-bob")
    resolver = SlackPrincipalResolver({"U07ABCDE123": p})
    # The Slack id resolves with case PRESERVED on both stored + incoming sides
    # (neither is lowercased), so the same-case id resolves...
    assert resolver.resolve_slack_id("U07ABCDE123").principal is p
    # ...and the stored key kept its case (a lowercased lookup is a different,
    # malformed id and does not resolve — see the case-mismatch test below).
    assert "U07ABCDE123" in resolver._by_slack_id  # noqa: SLF001 - structural check
    assert "u07abcde123" not in resolver._by_slack_id  # noqa: SLF001


def test_slack_id_case_mismatch_does_not_resolve():
    # Case-significant: a lowercased variant is a different (malformed) id and
    # MUST NOT resolve to the stored uppercase-shaped principal.
    p = _principal("d-bob")
    resolver = SlackPrincipalResolver({"U07ABCDE123": p})
    outcome = resolver.resolve_slack_id("u07abcde123")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT


def test_unknown_slack_id_resolves_to_reject():
    resolver = SlackPrincipalResolver({"U07ABCDE123": _principal("d-alice")})
    outcome = resolver.resolve_slack_id("U99ZZZZ999")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT


def test_malformed_incoming_slack_id_fails_closed_to_reject():
    # A malformed attribution id fails closed (REJECT) rather than raising.
    resolver = SlackPrincipalResolver({"U07ABCDE123": _principal("d-alice")})
    outcome = resolver.resolve_slack_id("not-a-slack-id")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT


# --- delegate_id is PRIMARY; slack_id is the secondary literal index --------


def test_delegate_id_is_primary_key_slack_id_is_secondary():
    # Same principal reachable via BOTH keys, proving the dual-keying, but
    # authenticate uses the delegate_id (primary) path.
    p = _principal("d-carol")
    resolver = SlackPrincipalResolver({"C0123456789": p})
    assert resolver.resolve_delegate_id("d-carol").principal is p
    assert resolver.resolve_slack_id("C0123456789").principal is p


# --- team/workspace id is in claims, NOT in the lookup key ------------------


def test_workspace_team_id_carried_in_claims_not_lookup_key():
    p = _principal("d-dave", team_id="T0WORKSPACE1")
    resolver = SlackPrincipalResolver({"U07DAVE0001": p})
    outcome = resolver.resolve_delegate_id("d-dave")
    assert outcome.accepted
    # team_id lives in claims (forward-compat for multi-workspace OAuth)...
    assert outcome.principal.claims["team_id"] == "T0WORKSPACE1"
    # ...and is NOT a resolution key: looking the team id up as a delegate_id or
    # a slack id does NOT resolve the principal.
    assert resolver.resolve_delegate_id("T0WORKSPACE1").principal is None
    assert resolver.resolve_slack_id("T0WORKSPACE1").principal is None


# --- closed enum + construction guards -------------------------------------


def test_disposition_enum_is_the_closed_conformance_set():
    assert {d.value for d in UnknownSenderDisposition} == {
        "Accept",
        "Reject",
        "EscalateToHuman",
    }


def test_resolver_rejects_non_principal_values():
    with pytest.raises(TypeError):
        SlackPrincipalResolver({"U07ABCDE123": "not-a-principal"})  # type: ignore[dict-item]


def test_resolver_rejects_non_dict():
    with pytest.raises(TypeError):
        SlackPrincipalResolver(["U07ABCDE123"])  # type: ignore[arg-type]


def test_resolver_rejects_malformed_stored_slack_id_key():
    # A malformed STORED key raises at construction (vs a malformed INCOMING id
    # on resolve_slack_id which fails closed) — the stored directory is trusted
    # input and MUST be well-formed.
    with pytest.raises(ValueError):
        SlackPrincipalResolver({"bad-key": _principal("d-eve")})


def test_resolution_outcome_accepted_property():
    accept = ResolutionOutcome(_principal(), UnknownSenderDisposition.ACCEPT)
    reject = ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
    assert accept.accepted is True
    assert reject.accepted is False
