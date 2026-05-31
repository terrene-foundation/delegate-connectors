# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for runtime composition (compose.py).

These prove compose BUILDS a valid, reusable DelegateRuntime with the real
shipped concretes (no mocks). The end-to-end ``runtime.execute()`` assertion
drives a protocol-faithful deterministic SMTP adapter (``_FakeSmtpSendFn``)
that satisfies the ``aiosmtplib.send`` return-shape contract and completes
without any network I/O — the same category as slack's ``_FakeAsyncWebClient``
injection. This is NOT a Tier-2 mock violation: the adapter is deterministic,
protocol-faithful, and injected through the production ``_send_fn`` seam
(not ``unittest.mock``). Fixed at kailash <= 2.28.1 (kailash-py#1182).
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


class _FakeSmtpSendFn:
    """Deterministic stand-in for ``aiosmtplib.send`` — satisfies the send protocol.

    Returns the same two-tuple ``aiosmtplib.send`` returns on a clean delivery:
    ``({}, "250 OK")``. An empty ``errors`` dict means all recipients accepted;
    ``response`` is the SMTP server greeting string. No network I/O; no external
    dependencies. Protocol-faithful deterministic adapter, NOT a mock.
    """

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(
        self, mime, *, hostname, port, username, password, use_tls, start_tls
    ):
        self.calls.append({"hostname": hostname, "port": port, "recipient": mime["To"]})
        return ({}, "250 OK")


def _transports():
    """Build SMTP + IMAP transports with deterministic adapters (no network)."""
    fake_send = _FakeSmtpSendFn()
    smtp = SmtpTransport(SmtpConfig(host="h", port=1025), _send_fn=fake_send)
    imap = ImapTransport(ImapConfig(host="h", port=1143))
    return smtp, imap


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


async def test_runtime_execute_end_to_end_completes():
    """End-to-end ``await runtime.execute(...)`` completes on kailash >= 2.28.0.

    Was strict-xfailed on kailash-py#1182 (runtime audit-emit signed the event
    payload bytes while ``AuditChainEngine`` verified the full entry signing bytes,
    so ``execute()`` failed at the first phase transition under any real verifier).
    Fixed at <= 2.28.1 (workspaces/whatsapp/journal/0008); the marker is removed
    and the assertion now holds. The SMTP transport is driven with a
    ``_FakeSmtpSendFn`` deterministic adapter so execute() completes without any
    network I/O — same category as slack's ``_FakeAsyncWebClient`` injection.
    """
    smtp, imap = _transports()
    composed = build_email_runtime(
        smtp=smtp, imap=imap, sender_email="alice@example.com"
    )
    result = await composed.runtime.execute(
        {"sender": "alice@example.com", "to": "b@x.com", "subject": "Hi", "body": "yo"}
    )
    assert result.taod_state.phase == "completed"
