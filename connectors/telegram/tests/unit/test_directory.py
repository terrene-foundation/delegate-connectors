# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the dual-keyed principal resolver + disposition."""

from __future__ import annotations

import pytest

from kailash.delegate.dispatch import Principal

from delegate_connectors.telegram.directory import (
    TelegramPrincipalResolver,
    UnknownSenderDisposition,
)


def _principal(delegate_id: str = "d-alice") -> Principal:
    return Principal(delegate_id=delegate_id, tenant_id="t1", claims={})


def _resolver(
    user_id: int | str = 123456789,
    chat_id: int | str = 987654321,
    delegate_id: str = "d-alice",
) -> TelegramPrincipalResolver:
    return TelegramPrincipalResolver([(user_id, chat_id, _principal(delegate_id))])


def test_known_user_id_resolves_to_principal_with_accept():
    p = _principal()
    resolver = TelegramPrincipalResolver([(123456789, 987654321, p)])
    outcome = resolver.resolve_user_id(123456789)
    assert outcome.accepted
    assert outcome.principal is p
    assert outcome.disposition is UnknownSenderDisposition.ACCEPT


def test_chat_id_resolves_to_same_principal_as_paired_user_id():
    p = _principal()
    resolver = TelegramPrincipalResolver([(123456789, 987654321, p)])
    by_user = resolver.resolve_user_id(123456789)
    by_chat = resolver.resolve_chat_id(987654321)
    assert by_user.principal is p
    assert by_chat.principal is p
    # Symmetric: the same Principal object is reachable both ways.
    assert by_user.principal is by_chat.principal


def test_delegate_id_resolves_to_same_principal():
    p = _principal("d-alice")
    resolver = TelegramPrincipalResolver([(123456789, 987654321, p)])
    assert resolver.resolve_delegate_id("d-alice").principal is p


def test_stringified_and_int_ids_collide_on_one_key():
    p = _principal()
    # Register with an int; resolve with the equivalent string (and vice versa).
    resolver = TelegramPrincipalResolver([(123456789, 987654321, p)])
    assert resolver.resolve_user_id("123456789").principal is p
    assert resolver.resolve_chat_id("987654321").principal is p


def test_negative_chat_id_is_a_valid_key():
    # Group / channel chat_ids are negative integers.
    p = _principal()
    resolver = TelegramPrincipalResolver([(123456789, -100200300, p)])
    assert resolver.resolve_chat_id(-100200300).principal is p
    assert resolver.resolve_chat_id("-100200300").principal is p


def test_unknown_user_id_resolves_to_reject_never_accept():
    resolver = _resolver()
    outcome = resolver.resolve_user_id(555000111)
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT
    assert outcome.disposition is not UnknownSenderDisposition.ACCEPT
    assert not outcome.accepted


def test_unknown_chat_id_and_delegate_id_resolve_to_reject():
    resolver = _resolver()
    assert resolver.resolve_chat_id(111222333).disposition is (
        UnknownSenderDisposition.REJECT
    )
    assert resolver.resolve_delegate_id("d-unknown").disposition is (
        UnknownSenderDisposition.REJECT
    )


def test_handle_never_resolves_even_when_id_is_registered():
    # @username is never a key: resolve_handle is always fail-closed Reject.
    resolver = _resolver()
    outcome = resolver.resolve_handle("@alice")
    assert outcome.principal is None
    assert outcome.disposition is UnknownSenderDisposition.REJECT
    assert not outcome.accepted


def test_handle_passed_to_id_resolvers_raises_not_resolves():
    # A @username handle is ref-unsafe; it must never silently miss as if it
    # were just an unknown id — passing it to an id resolver raises.
    resolver = _resolver()
    with pytest.raises(ValueError):
        resolver.resolve_user_id("@alice")
    with pytest.raises(ValueError):
        resolver.resolve_chat_id("@alice")


def test_disposition_enum_is_the_closed_conformance_set():
    assert {d.value for d in UnknownSenderDisposition} == {
        "Accept",
        "Reject",
        "EscalateToHuman",
    }


def test_resolver_rejects_non_principal_values():
    with pytest.raises(TypeError):
        TelegramPrincipalResolver([(1, 2, "not-a-principal")])  # type: ignore[list-item]


def test_resolver_rejects_malformed_entry():
    with pytest.raises(TypeError):
        TelegramPrincipalResolver([(1, 2)])  # type: ignore[list-item]


def test_bool_id_is_rejected():
    with pytest.raises(TypeError):
        TelegramPrincipalResolver([(True, 2, _principal())])
