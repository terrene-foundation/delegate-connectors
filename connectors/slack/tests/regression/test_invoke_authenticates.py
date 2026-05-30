# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — ``invoke`` authenticates FIRST (fail-closed Reject before send).

An unknown principal MUST raise ``ConnectorAuthenticationError`` (fail-closed
Reject) BEFORE any ``chat.postMessage`` fires — the record-and-assert double
proves ZERO posts were recorded. A known principal authenticates and the post
proceeds exactly once.

Behavioral: call the real ``invoke``, assert the raise/return AND the double's
recorded-post count. NEVER source-grep.
"""

from __future__ import annotations

import uuid

import pytest

from kailash.delegate import DelegateIdentity

from delegate_connectors.slack.connector import ConnectorAuthenticationError

from .conftest import CHANNEL_ID

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


async def test_unknown_principal_rejects_and_zero_posts(slack):
    """Unknown identity → ConnectorAuthenticationError, ZERO chat.postMessage."""
    conn = slack["connector"]
    envelope = slack["envelope"]
    double = slack["double"]

    unknown = DelegateIdentity(
        delegate_id=uuid.uuid4(),
        sovereign_ref="s",
        role_binding_ref="r",
        genesis_ref="g",
    )

    with pytest.raises(ConnectorAuthenticationError, match="Reject"):
        await conn.invoke(
            {"channel": CHANNEL_ID, "text": "should not fire"},
            identity=unknown,
            envelope=envelope,
        )

    # The fail-closed gate held: ZERO posts reached the double over the socket.
    assert double.posts == [], "an auth Reject MUST fire BEFORE any chat.postMessage"
    # No external side-effect recorded in the ledger either.
    assert conn.ledger.records == ()


async def test_known_principal_authenticates_and_posts_once(slack):
    """Control: a known principal authenticates and the post fires exactly once.

    Confirms the Reject gate is the ONLY thing blocking sends above (not some
    unrelated wiring failure): with a known identity the double records exactly
    one post.
    """
    conn = slack["connector"]
    identity = slack["identity"]
    envelope = slack["envelope"]
    double = slack["double"]

    result = await conn.invoke(
        {"channel": CHANNEL_ID, "text": "hello team"},
        identity=identity,
        envelope=envelope,
    )

    assert len(double.posts) == 1
    assert double.posts[0].channel == CHANNEL_ID
    assert result.external_side_effect is True
