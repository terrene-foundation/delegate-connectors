# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures for the WhatsApp security regression suite.

Builds a REAL ``WhatsAppConnector`` — the real ``kailash.delegate.dispatch.
Connector`` subclass, a real Ed25519 signing key + shipped ``Ed25519Verifier``,
a real ``WhatsAppCloudApi`` transport whose HTTP byte stream terminates at the
in-process ``CloudApiDouble`` (NO mock of the connector / Cloud API client; the
double is a Protocol-satisfying deterministic adapter per ``rules/testing.md``
§ "Protocol Adapters" + WA-ADR-5).

The connector contract is never stubbed: the only external boundary is the
``httpx`` byte stream, terminated by ``httpx.MockTransport`` inside the double.

Credentials come from ``monkeypatch.setenv`` (the ``WHATSAPP_PII_HMAC_KEY``
startup gate refuses construction without it) — never hardcoded into a test
body beyond the deterministic non-secret test fixtures here.
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
from delegate_connectors.whatsapp.templates import ServiceWindowTracker, TemplateGate
from delegate_connectors.whatsapp.webhook import WebhookConfig, WebhookIngest

#: A known sender's bare-digit E.164. Used as the raw-PII probe target across the
#: redaction regressions: the suite asserts these literal digits are ABSENT from
#: every serialized audit / ledger surface.
SENDER_PHONE = "14155550100"

#: The approved-template name the gate allowlists.
APPROVED_TEMPLATE = "order_update"


@pytest.fixture
def transport_spy(cloud_api_double):
    """The in-process Cloud API double, used as a transport call-spy.

    ``cloud_api_double`` is provided by the top-level ``tests/conftest.py``
    (re-exported from ``tests/integration/_cloud_api_double.py``). Every
    ``POST .../messages`` the REAL production transport emits is recorded on
    ``.requests``; a Reject-gate test asserts ``.requests == []`` to prove no
    send fired.
    """
    return cloud_api_double


@pytest.fixture
def wa(monkeypatch, transport_spy):
    """A fully-wired WhatsAppConnector + identity/verifier/envelope bundle.

    The connector's Cloud API transport is the REAL ``WhatsAppCloudApi`` over a
    REAL ``httpx.AsyncClient`` whose byte stream terminates at ``transport_spy``
    — so a fired send is a recorded request, and zero recorded requests proves
    no send occurred.
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
        delegate_id=str(delegate_id),
        tenant_id="t1",
        claims={"phone": SENDER_PHONE},
    )
    resolver = WhatsAppPrincipalResolver({SENDER_PHONE: principal})

    window_tracker = ServiceWindowTracker()
    # Open the sender's 24h window so a free-form invoke is allowed by default;
    # individual Reject-gate tests build their own closed-window tracker.
    window_tracker.record_inbound(SENDER_PHONE)
    template_gate = TemplateGate({APPROVED_TEMPLATE}, window_tracker)

    # REAL transport over a REAL httpx client terminating at the double.
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

    return {
        "connector": connector,
        "identity": identity,
        "verifier": verifier,
        "envelope": envelope,
        "delegate_id": delegate_id,
        "signing_key": sk,
        "window_tracker": window_tracker,
        "transport_spy": transport_spy,
    }
