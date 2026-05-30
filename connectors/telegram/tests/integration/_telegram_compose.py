# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Composed-runtime helpers for the Tier-2 + regression tiers (importable by name).

The helpers live in this module (not in ``conftest.py``) so the test modules can
``from _telegram_compose import compose_fresh`` — a sibling ``conftest`` is NOT
importable by name (it resolves to the nearest conftest on the path). Mirrors
the WhatsApp connector's ``_cloud_api_double`` / ``_live_meta`` split.

All helpers build the REAL :class:`TelegramTransport` over a REAL
:class:`httpx.AsyncClient` whose byte stream terminates at the in-process Bot
API double — NO mock at the connector boundary.
"""

from __future__ import annotations

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _botapi_double import BotApiDouble

from delegate_connectors.telegram.compose import (
    ComposedTelegramRuntime,
    build_telegram_runtime,
)
from delegate_connectors.telegram.transport import TelegramConfig, TelegramTransport
from kailash.delegate.dispatch import Principal

SENDER_USER_ID = 424242
SENDER_CHAT_ID = 555000
TENANT = "tenant-telegram-v0"


def compose_over_double(
    double: BotApiDouble,
    client: httpx.AsyncClient,
    sk: Ed25519PrivateKey,
) -> ComposedTelegramRuntime:
    """Compose the real runtime with the transport pointed at ``double`` via ``client``.

    The composed dispatch identity's ``delegate_id`` is a UUID; register it as a
    resolvable principal so the ``invoke`` auth-FIRST gate accepts it (the
    resolver keys on stringified user_id, AND on the principal's delegate_id —
    which is the view ``authenticate`` uses). The known inbound sender is
    ``SENDER_USER_ID``.

    Credentials come from the env (set by the package autouse
    ``_telegram_test_env`` fixture); ``TelegramConfig.from_env`` reads them.
    """
    transport = TelegramTransport(TelegramConfig.from_env(), client=client)
    composed = build_telegram_runtime(
        transport=transport,
        sender_user_id=SENDER_USER_ID,
        sender_chat_id=SENDER_CHAT_ID,
        sender_principal_tenant=TENANT,
        signing_key=sk,
    )
    # build_telegram_runtime registers a Principal whose delegate_id is the
    # SENDER_USER_ID-keyed principal; but authenticate() resolves the dispatch
    # identity by ITS delegate_id (a fresh UUID). Register that UUID too so the
    # auth-FIRST invoke gate accepts the composed dispatch identity.
    principal = Principal(
        delegate_id=str(composed.identity.delegate_id),
        tenant_id=TENANT,
        claims={"user_id": SENDER_USER_ID, "chat_id": SENDER_CHAT_ID},
    )
    composed.connector._resolver._by_delegate_id[str(composed.identity.delegate_id)] = (
        principal
    )
    return composed


def compose_fresh(
    double: BotApiDouble, sk: Ed25519PrivateKey | None = None
) -> tuple[ComposedTelegramRuntime, httpx.AsyncClient]:
    """Build a fresh composed runtime over ``double``; return ``(composed, client)``.

    The caller owns the returned ``httpx.AsyncClient`` and MUST ``aclose()`` it
    in teardown so no ``ResourceWarning`` (unclosed transport) is emitted.
    """
    key = sk or Ed25519PrivateKey.generate()
    client = double.client()
    composed = compose_over_double(double, client, key)
    return composed, client
