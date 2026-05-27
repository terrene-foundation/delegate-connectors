# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for principal resolution + unknown-sender disposition."""

from __future__ import annotations

import pytest

from kailash.delegate.dispatch import Principal

from delegate_connectors.email.directory import (
    EmailPrincipalResolver,
    UnknownSenderDisposition,
    normalize_address,
)


def _principal(delegate_id: str = "d-alice") -> Principal:
    return Principal(delegate_id=delegate_id, tenant_id="t1", claims={})


def test_normalize_address_strips_display_name_and_lowercases():
    assert normalize_address("Alice <ALICE@Example.com>") == "alice@example.com"
    assert normalize_address("  Bob@EXAMPLE.COM  ") == "bob@example.com"


def test_known_address_resolves_to_principal_with_accept():
    p = _principal()
    resolver = EmailPrincipalResolver({"alice@example.com": p})
    outcome = resolver.resolve("alice@example.com")
    assert outcome.accepted
    assert outcome.principal is p
    assert outcome.disposition is UnknownSenderDisposition.ACCEPT


def test_normalization_round_trips_case_and_display_name():
    p = _principal()
    resolver = EmailPrincipalResolver({"Alice <ALICE@Example.com>": p})
    # A differently-cased, display-named incoming address resolves the same.
    assert resolver.resolve("Foo Bar <alice@example.com>").principal is p


def test_unknown_address_resolves_to_reject_never_accept():
    resolver = EmailPrincipalResolver({"alice@example.com": _principal()})
    outcome = resolver.resolve("eve@evil.com")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT
    assert outcome.disposition is not UnknownSenderDisposition.ACCEPT
    assert not outcome.accepted


def test_resolve_by_delegate_id_known_and_unknown():
    p = _principal("d-alice")
    resolver = EmailPrincipalResolver({"alice@example.com": p})
    assert resolver.resolve_delegate_id("d-alice").principal is p
    unknown = resolver.resolve_delegate_id("d-unknown")
    assert unknown.principal is None
    assert unknown.disposition is UnknownSenderDisposition.REJECT


def test_disposition_enum_is_the_closed_conformance_set():
    assert {d.value for d in UnknownSenderDisposition} == {
        "Accept",
        "Reject",
        "EscalateToHuman",
    }


def test_resolver_rejects_non_principal_values():
    with pytest.raises(TypeError):
        EmailPrincipalResolver({"a@b.com": "not-a-principal"})  # type: ignore[dict-item]
