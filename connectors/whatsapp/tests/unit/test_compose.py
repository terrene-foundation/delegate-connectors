# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for runtime composition (compose.py).

These prove ``build_whatsapp_runtime`` BUILDS a valid, reusable DelegateRuntime
with the real shipped concretes (no mocks) and that the connector's own receipts
verify under the composed verifier. The end-to-end ``runtime.execute()``
assertion is gated on the SDK fix (kailash-py#1182, documented in the compose.py
module docstring) and is marked strict-xfail with a precise reason — NOT skipped
silently and NOT faked. Composition itself (up to build_whatsapp_runtime) PASSES;
only ``execute()`` is xfail.

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
from delegate_connectors.whatsapp.redaction import PII_HMAC_KEY_ENV
from delegate_connectors.whatsapp.webhook import WebhookConfig, WebhookIngest

pytestmark = pytest.mark.asyncio

_SENDER_PHONE = "+14155550100"


@pytest.fixture(autouse=True)
def _pii_key(monkeypatch):
    # The connector __init__ startup gate runs inside build_whatsapp_runtime.
    monkeypatch.setenv(PII_HMAC_KEY_ENV, "test-pii-hmac-key-min-len")


def _cloud_api() -> WhatsAppCloudApi:
    return WhatsAppCloudApi(
        WhatsAppCloudConfig(
            access_token="tok", phone_number_id="1", graph_version="18.0"
        )
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


@pytest.mark.xfail(
    strict=True,
    reason="kailash-py#1182 audit-emit signing-bytes bug",
)
async def test_runtime_execute_end_to_end_gated_on_sdk_fix():
    composed = build_whatsapp_runtime(
        cloud_api=_cloud_api(),
        ingest=_ingest(),
        sender_phone=_SENDER_PHONE,
        approved_templates={"order_update"},
    )
    result = await composed.runtime.execute({"to": _SENDER_PHONE, "text": "hi"})
    # When the SDK is fixed this assertion will hold and the strict xfail flips
    # to XPASS (forcing the marker to be removed once the SDK ships the fix).
    assert result.taod_state.phase == "completed"
