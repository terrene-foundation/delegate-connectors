# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression: the auth gate fires BEFORE any Bot API send (T-ADR-2).

Locks the invariant that an unknown sender is rejected on the dispatch hot path
BEFORE any external Bot API call — the auth check is upstream of the send, so a
Reject produces ZERO outbound HTTP. Behavioral: drives the real ``invoke`` path
and asserts (a) an unknown identity raises and the Bot API double recorded ZERO
sendMessage requests, and (b) a known identity authenticates and exactly ONE
sendMessage fires.
"""

from __future__ import annotations

import uuid

import pytest

from delegate_connectors.telegram.connector import ConnectorAuthenticationError

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


async def test_unknown_sender_rejected_before_any_send(
    telegram_regression_composed, botapi_double
):
    """An unknown delegate identity raises and triggers ZERO Bot API sends."""
    composed = telegram_regression_composed

    bogus_identity = composed.identity.__class__(
        delegate_id=uuid.uuid4(),
        sovereign_ref="bogus",
        role_binding_ref="bogus",
        genesis_ref="bogus",
        principal_kind="delegate",
    )

    with pytest.raises(ConnectorAuthenticationError):
        await composed.connector.invoke(
            {"chat_id": 555000, "text": "should never send"},
            identity=bogus_identity,
            envelope=composed.dispatch_surface.envelope,
        )

    # The Reject fired upstream of any send — the double saw zero sendMessage.
    assert botapi_double.send_requests == []
    assert botapi_double.delivered == []


async def test_known_sender_authenticates_and_send_proceeds_once(
    telegram_regression_composed, botapi_double
):
    """A known identity authenticates and exactly ONE sendMessage fires."""
    composed = telegram_regression_composed

    result = await composed.connector.invoke(
        {"chat_id": 555000, "text": "authorized hello"},
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    assert result.external_side_effect is True
    # Exactly one send transited the double.
    assert len(botapi_double.send_requests) == 1
    assert len(botapi_double.delivered) == 1
    assert botapi_double.delivered[0]["chat_id"] == 555000
    assert botapi_double.delivered[0]["text"] == "authorized hello"
