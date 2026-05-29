# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — binding security property 3: template / window Reject gate.

Each pre-flight Reject MUST block the send BEFORE any Cloud API call fires:

- A free-form message to a recipient OUTSIDE the open 24h customer-service
  window → ``OutsideServiceWindowError`` and ZERO transport calls.
- A send naming a template NOT in the approved-template allowlist →
  ``TemplateNotApprovedError`` and ZERO transport calls.

The "zero transport calls" assertion is behavioral: the connector's REAL
``WhatsAppCloudApi`` transport runs over a REAL ``httpx.AsyncClient`` whose byte
stream terminates at the in-process ``CloudApiDouble`` spy. A Reject means the
spy recorded ZERO ``POST .../messages`` requests.

Invariant 3: each Reject gate blocks the send (transport spy records zero calls).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import (
    DelegateIdentity,
    Ed25519Verifier,
    PrincipalDirectory,
)
from kailash.delegate.dispatch import Principal
from kailash.delegate.envelope import DelegateConstraintEnvelope
from kailash.delegate.types import DelegateGenesisRecord
from kailash.trust.chain import AuthorityType, GenesisRecord
from kailash.trust.envelope import ConstraintEnvelope

from delegate_connectors.whatsapp.cloud_api import (
    WhatsAppCloudApi,
    WhatsAppCloudConfig,
)
from delegate_connectors.whatsapp.connector import WhatsAppConnector
from delegate_connectors.whatsapp.directory import WhatsAppPrincipalResolver
from delegate_connectors.whatsapp.redaction import PII_HMAC_KEY_ENV
from delegate_connectors.whatsapp.templates import (
    OutsideServiceWindowError,
    ServiceWindowTracker,
    TemplateGate,
    TemplateNotApprovedError,
)
from delegate_connectors.whatsapp.webhook import WebhookConfig, WebhookIngest

from .conftest import APPROVED_TEMPLATE, SENDER_PHONE

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


def _build_connector(monkeypatch, transport_spy, *, window_open: bool):
    """A real connector whose 24h window is open or closed per ``window_open``.

    The transport is the REAL ``WhatsAppCloudApi`` over a REAL ``httpx`` client
    terminating at ``transport_spy`` — a fired send is a recorded request.
    """
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-pii-hmac-key-min-len")

    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key().public_bytes_raw()
    delegate_id = uuid.uuid4()
    identity = DelegateIdentity(
        delegate_id=delegate_id,
        sovereign_ref="sovereign-1",
        role_binding_ref="rb-1",
        genesis_ref="g-1",
    )
    directory = PrincipalDirectory(
        identities=(identity,), verification_keys={delegate_id: pk}
    )
    verifier = Ed25519Verifier(directory)
    principal = Principal(
        delegate_id=str(delegate_id), tenant_id="t1", claims={"phone": SENDER_PHONE}
    )
    resolver = WhatsAppPrincipalResolver({SENDER_PHONE: principal})

    window_tracker = ServiceWindowTracker()
    if window_open:
        window_tracker.record_inbound(SENDER_PHONE)
    # If window_open is False we DO NOT record an inbound — the window stays
    # closed, so a free-form send must be rejected pre-flight.
    template_gate = TemplateGate({APPROVED_TEMPLATE}, window_tracker)

    cloud_api = WhatsAppCloudApi(
        WhatsAppCloudConfig(
            access_token="tok", phone_number_id="1", graph_version="18.0"
        ),
        client=transport_spy.client(),
    )
    connector = WhatsAppConnector(
        cloud_api=cloud_api,
        ingest=WebhookIngest(
            WebhookConfig(app_secret="sek", verify_token="vt"),
            window_sink=window_tracker.record_inbound,
        ),
        resolver=resolver,
        template_gate=template_gate,
        signing_key=sk,
        verifier=verifier,
        tenant_id="t1",
    )

    genesis_block = GenesisRecord(
        id="gb",
        agent_id=str(delegate_id),
        authority_id="a",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    dgen = DelegateGenesisRecord(
        block=genesis_block, spec_version="0", capabilities=("whatsapp.send",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)
    return connector, identity, envelope


async def test_freeform_outside_window_rejects_and_no_send(monkeypatch, transport_spy):
    """Free-form send outside the 24h window: OutsideServiceWindowError, zero sends."""
    conn, identity, envelope = _build_connector(
        monkeypatch, transport_spy, window_open=False
    )

    with pytest.raises(OutsideServiceWindowError):
        await conn.invoke(
            {"to": SENDER_PHONE, "text": "hello"},
            identity=identity,
            envelope=envelope,
        )

    assert (
        transport_spy.requests == []
    ), "a window-Reject MUST fire BEFORE any Cloud API send"
    # No external side-effect was recorded in the ledger either.
    assert conn.ledger.records == ()


async def test_unapproved_template_rejects_and_no_send(monkeypatch, transport_spy):
    """Un-approved template: TemplateNotApprovedError, zero sends."""
    conn, identity, envelope = _build_connector(
        monkeypatch, transport_spy, window_open=True
    )

    with pytest.raises(TemplateNotApprovedError):
        await conn.invoke(
            {"to": SENDER_PHONE, "template_name": "not_on_the_allowlist"},
            identity=identity,
            envelope=envelope,
        )

    assert (
        transport_spy.requests == []
    ), "an un-approved-template Reject MUST fire BEFORE any Cloud API send"
    assert conn.ledger.records == ()


async def test_approved_template_outside_window_sends(monkeypatch, transport_spy):
    """Control: an approved template is window-exempt — the send DOES fire.

    Confirms the Reject gate is the ONLY thing blocking sends above (not some
    unrelated wiring failure): with an approved template and a closed window the
    transport spy records exactly one request.
    """
    conn, identity, envelope = _build_connector(
        monkeypatch, transport_spy, window_open=False
    )

    result = await conn.invoke(
        {"to": SENDER_PHONE, "template_name": APPROVED_TEMPLATE},
        identity=identity,
        envelope=envelope,
    )

    assert len(transport_spy.requests) == 1
    assert result.external_side_effect is True


async def test_freeform_inside_window_sends(monkeypatch, transport_spy):
    """Control: a free-form send INSIDE the open window DOES fire (one request)."""
    conn, identity, envelope = _build_connector(
        monkeypatch, transport_spy, window_open=True
    )

    result = await conn.invoke(
        {"to": SENDER_PHONE, "text": "hello"},
        identity=identity,
        envelope=envelope,
    )

    assert len(transport_spy.requests) == 1
    assert result.external_side_effect is True
