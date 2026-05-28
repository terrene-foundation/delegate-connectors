# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for principal resolution + unknown-sender disposition."""

from __future__ import annotations

import pytest

from kailash.delegate.dispatch import Principal

from delegate_connectors.whatsapp.directory import (
    ResolutionOutcome,
    UnknownSenderDisposition,
    WhatsAppPrincipalResolver,
)


def _principal(delegate_id: str = "d-alice") -> Principal:
    return Principal(delegate_id=delegate_id, tenant_id="t1", claims={})


def test_known_delegate_id_resolves_to_principal_with_accept():
    p = _principal("d-alice")
    resolver = WhatsAppPrincipalResolver({"+14155550100": p})
    outcome = resolver.resolve_delegate_id("d-alice")
    assert isinstance(outcome, ResolutionOutcome)
    assert outcome.accepted
    assert outcome.principal is p
    assert outcome.principal.delegate_id == "d-alice"
    assert outcome.principal.tenant_id == "t1"
    assert outcome.principal.claims == {}
    assert outcome.disposition is UnknownSenderDisposition.ACCEPT


def test_unknown_delegate_id_resolves_to_reject_never_accept():
    resolver = WhatsAppPrincipalResolver({"+14155550100": _principal()})
    outcome = resolver.resolve_delegate_id("d-unknown")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT
    assert outcome.disposition is not UnknownSenderDisposition.ACCEPT
    assert not outcome.accepted


def test_known_phone_resolves_to_principal_with_accept():
    p = _principal("d-alice")
    resolver = WhatsAppPrincipalResolver({"+14155550100": p})
    assert resolver.resolve_phone("+14155550100").principal is p


def test_unknown_phone_resolves_to_reject():
    resolver = WhatsAppPrincipalResolver({"+14155550100": _principal()})
    outcome = resolver.resolve_phone("+19998887777")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT


def test_phone_normalization_round_trips_across_surface_forms():
    p = _principal()
    # Stored as a +-prefixed, separator-laden surface form...
    resolver = WhatsAppPrincipalResolver({"+1 (415) 555-0100": p})
    # ...resolves the same from a bare-digit wa_id (the inbound surface form).
    assert resolver.resolve_phone("14155550100").principal is p
    assert resolver.resolve_phone("+14155550100").principal is p


def test_unnormalizable_phone_fails_closed_to_reject():
    resolver = WhatsAppPrincipalResolver({"+14155550100": _principal()})
    outcome = resolver.resolve_phone("garbage")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT


def test_disposition_enum_is_the_closed_conformance_set():
    assert {d.value for d in UnknownSenderDisposition} == {
        "Accept",
        "Reject",
        "EscalateToHuman",
    }


def test_resolver_rejects_non_principal_values():
    with pytest.raises(TypeError):
        WhatsAppPrincipalResolver({"+14155550100": "not-a-principal"})  # type: ignore[dict-item]
