# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for runtime composition (compose.py).

These prove ``build_whatsapp_runtime`` BUILDS a valid, reusable DelegateRuntime
with the real shipped concretes (no mocks) and that the connector's own receipts
verify under the composed verifier. The end-to-end ``runtime.execute()``
assertion now passes at kailash >= 2.28.1 (kailash-py#1182 fixed) and is no
longer xfailed.

The execute() test pre-warms the service window for the recipient via the
composed connector's window tracker so a freeform text payload passes the
pre-flight TemplateGate without requiring an approved-template send (WhatsApp
only allows freeform text within an open 24h customer-service window; the
window tracker is injectable, so this is deterministic and requires no real
WhatsApp infrastructure).

The Cloud API call itself is terminated at the in-process CloudApiDouble so no
real HTTP request leaves the unit test.

The PII HMAC key is set via ``monkeypatch.setenv`` because the connector's
``__init__`` startup gate (invoked inside ``build_whatsapp_runtime``) refuses to
construct without it.
"""

from __future__ import annotations

import pytest

from kailash.delegate import DelegateRuntime, DispatchSurface, Ed25519Verifier

from delegate_connectors.whatsapp.cloud_api import (
    WhatsAppCloudApi,
    WhatsAppCloudConfig,
)
from delegate_connectors.whatsapp.compose import (
    ComposedWhatsAppRuntime,
    WhatsAppV0Signature,
    build_whatsapp_runtime,
)
from delegate_connectors.whatsapp.redaction import PII_HMAC_KEY_ENV, normalize_e164
from delegate_connectors.whatsapp.webhook import WebhookConfig, WebhookIngest

pytestmark = pytest.mark.asyncio

_SENDER_PHONE = "+14155550100"


@pytest.fixture(autouse=True)
def _pii_key(monkeypatch):
    # The connector __init__ startup gate runs inside build_whatsapp_runtime.
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-pii-hmac-key-min-len")


def _cloud_api() -> WhatsAppCloudApi:
    # Inject the in-process double so the execute() test terminates at the
    # double rather than opening a real HTTPS connection to Meta.
    from _cloud_api_double import CloudApiDouble

    return WhatsAppCloudApi(
        WhatsAppCloudConfig(
            access_token="tok", phone_number_id="1", graph_version="18.0"
        ),
        client=CloudApiDouble().client(),
    )


def _ingest() -> WebhookIngest:
    return WebhookIngest(WebhookConfig(app_secret="sek", verify_token="vt"))


async def test_build_whatsapp_runtime_constructs_real_runtime():
    composed = build_whatsapp_runtime(
        cloud_api=_cloud_api(),
        ingest=_ingest(),
        sender_phone=_SENDER_PHONE,
        approved_templates={"order_update"},
    )
    assert isinstance(composed, ComposedWhatsAppRuntime)
    assert isinstance(composed.runtime, DelegateRuntime)
    assert isinstance(composed.dispatch_surface, DispatchSurface)
    assert isinstance(composed.verifier, Ed25519Verifier)


async def test_build_whatsapp_runtime_is_reusable_independent_instances():
    a = build_whatsapp_runtime(
        cloud_api=_cloud_api(), ingest=_ingest(), sender_phone=_SENDER_PHONE
    )
    b = build_whatsapp_runtime(
        cloud_api=_cloud_api(), ingest=_ingest(), sender_phone="+14155550101"
    )
    assert a.identity.delegate_id != b.identity.delegate_id


async def test_v0_signature_input_schema_is_the_whatsapp_send_contract():
    sig = WhatsAppV0Signature()
    assert sig.name == "whatsapp-send"
    assert set(sig.input_schema) == {"to", "text"}
    assert set(sig.output_schema) == {"wamid", "wa_id", "to"}


async def test_connector_receipts_verify_under_composed_verifier():
    """The verifier compose returns verifies the connector's own receipts."""
    composed = build_whatsapp_runtime(
        cloud_api=_cloud_api(),
        ingest=_ingest(),
        sender_phone=_SENDER_PHONE,
        approved_templates={"order_update"},
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
    """End-to-end ``await runtime.execute(...)`` completes on kailash >= 2.28.1.

    kailash-py#1182 (audit-emit signed the event payload bytes while
    AuditChainEngine verified the full entry signing bytes) is fixed at
    <= 2.28.1. The xfail marker is removed; the assertion now holds.

    The service window for the recipient is pre-warmed via the composed
    connector's window tracker so a freeform text payload passes the pre-flight
    TemplateGate (WhatsApp requires either an approved template or an open 24h
    customer-service window for freeform text; the window tracker is injectable
    for deterministic testing). The Cloud API call terminates at the injected
    in-process CloudApiDouble — no real HTTP request leaves the test.
    """
    composed = build_whatsapp_runtime(
        cloud_api=_cloud_api(),
        ingest=_ingest(),
        sender_phone=_SENDER_PHONE,
        approved_templates={"order_update"},
    )
    # Pre-warm the service window so the freeform payload is gate-allowed.
    recipient_normalized = normalize_e164(_SENDER_PHONE)
    composed.connector._template_gate._window.record_inbound(recipient_normalized)

    result = await composed.runtime.execute({"to": _SENDER_PHONE, "text": "hi"})
    assert result.taod_state.phase == "completed"
