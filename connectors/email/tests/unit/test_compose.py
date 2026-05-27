# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for runtime composition (compose.py).

These prove compose BUILDS a valid, reusable DelegateRuntime with the real
shipped concretes (no mocks). The end-to-end ``runtime.execute()`` assertion is
gated on an SDK fix (see ``workspaces/email/journal/0005-GAP-*``) and is marked
xfail with a precise reason — NOT skipped silently and NOT faked.
"""

from __future__ import annotations

import pytest

from kailash.delegate import DelegateRuntime, DispatchSurface

from delegate_connectors.email.compose import (
    ComposedEmailRuntime,
    EmailV0Signature,
    build_email_runtime,
)
from delegate_connectors.email.imap import ImapConfig, ImapTransport
from delegate_connectors.email.smtp import SmtpConfig, SmtpTransport

pytestmark = pytest.mark.asyncio


def _transports():
    return (
        SmtpTransport(SmtpConfig(host="h", port=1025)),
        ImapTransport(ImapConfig(host="h", port=1143)),
    )


async def test_build_email_runtime_constructs_real_runtime():
    smtp, imap = _transports()
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )
    assert isinstance(composed, ComposedEmailRuntime)
    assert isinstance(composed.runtime, DelegateRuntime)
    assert isinstance(composed.dispatch_surface, DispatchSurface)


async def test_build_email_runtime_is_reusable_independent_instances():
    smtp, imap = _transports()
    a = build_email_runtime(smtp=smtp, imap=imap, sender_email="a@x.com")
    b = build_email_runtime(smtp=smtp, imap=imap, sender_email="b@x.com")
    assert a.identity.delegate_id != b.identity.delegate_id


async def test_v0_signature_input_schema_is_the_email_send_contract():
    sig = EmailV0Signature()
    assert sig.name == "email-send"
    assert set(sig.input_schema) == {"sender", "to", "subject", "body"}


async def test_connector_receipts_verify_under_composed_verifier():
    """The verifier compose returns verifies the connector's own receipts."""
    smtp, imap = _transports()
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )

    async def thunk():
        return {"sent": True}

    envelope = await composed.connector.write(
        thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    assert composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )


@pytest.mark.xfail(
    reason=(
        "SDK bug (kailash.delegate): runtime/dispatch audit-emit signs payload "
        "bytes but AuditChainEngine verifies the full entry signing bytes, so "
        "runtime.execute() fails at the first phase transition under any real "
        "verifier. See workspaces/email/journal/0005-GAP-*. The connector's own "
        "receipts verify (test above); this is gated on the SDK fix."
    ),
    strict=True,
)
async def test_runtime_execute_end_to_end_gated_on_sdk_fix():
    smtp, imap = _transports()
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )
    result = await composed.runtime.execute(
        {"sender": "alice@example.com", "to": "b@x.com", "subject": "Hi", "body": "yo"}
    )
    # When the SDK is fixed this assertion will hold and the xfail flips to
    # XPASS (strict=True turns an unexpected pass into a failure, forcing the
    # xfail marker to be removed once the SDK ships the fix).
    assert result.taod_state.phase == "completed"
