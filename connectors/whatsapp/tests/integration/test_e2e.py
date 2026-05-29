# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-3 e2e: compose a DelegateRuntime and drive it against the Cloud API double.

The end-to-end ``runtime.execute()`` OUTCOME assertion (a COMPLETED run carrying
a verifiable SignedActionEnvelope) is GATED on an SDK fix: the shipped
``kailash.delegate`` runtime audit-emit path signs the event PAYLOAD bytes while
``AuditChainEngine.emit_event`` verifies the FULL audit-entry signing bytes, so
``execute()`` fails at the first phase transition under ANY real verifier
(kailash-py#1182, compose.py module docstring "KNOWN SDK BLOCKER"). The outcome
assertion is a STRICT xfail — when the SDK ships the fix it flips to XPASS and
forces the marker's removal.

Intra-impl receipt determinism is asserted SEPARATELY via
``assert_receipts_agree``: it holds regardless of the phase outcome, which is
exactly the cross-impl-agreement contract the spec asks v0 to demonstrate.

This is Tier-2 against the in-process protocol-faithful Cloud API double
(WA-ADR-5). The opt-in Tier-3 live Meta sandbox test lives below behind the
``requires_live_meta`` gate — it SKIPS with a "cannot execute" reason when no
live ``WHATSAPP_*`` creds are present (journal 0003 Gap A), never a mock.
"""

from __future__ import annotations

import pytest

from kailash.delegate import assert_receipts_agree

from delegate_connectors.whatsapp.cloud_api import (
    WhatsAppCloudApi,
    WhatsAppCloudConfig,
)
from delegate_connectors.whatsapp.compose import build_whatsapp_runtime
from delegate_connectors.whatsapp.connector import verify_action_envelope
from delegate_connectors.whatsapp.webhook import WebhookIngest

from _live_meta import requires_live_meta

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_SENDER_PHONE = "+14155550000"
_RECIPIENT = "+14155551234"
_APPROVED_TEMPLATE = "order_update"


def _composed(cloud_api_double):
    """Build the real composed runtime over the in-process double.

    Uses an approved-template send so the dispatch path is window-exempt
    (no inbound-window priming needed for a deterministic e2e); the template
    gate is the REAL gate, exercised end-to-end.
    """
    config = WhatsAppCloudConfig.from_env()
    cloud_api = WhatsAppCloudApi(config, client=cloud_api_double.client())
    ingest = WebhookIngest.from_env()
    return build_whatsapp_runtime(
        cloud_api=cloud_api,
        ingest=ingest,
        sender_phone=_SENDER_PHONE,
        approved_templates=(_APPROVED_TEMPLATE,),
    )


def _send_payload() -> dict[str, str]:
    return {
        "to": _RECIPIENT,
        "text": "",
        "template_name": _APPROVED_TEMPLATE,
    }


@pytest.mark.xfail(
    reason=(
        "SDK bug (kailash-py#1182): the runtime audit-emit path signs the event "
        "payload bytes but AuditChainEngine verifies the full entry signing "
        "bytes; runtime.execute() fails at the first phase transition under any "
        "real verifier. See compose.py 'KNOWN SDK BLOCKER'. The connector's own "
        "read/write receipts verify (Tier-1 + test_send_roundtrip); this e2e "
        "outcome is gated on the SDK fix."
    ),
    strict=True,
)
async def test_runtime_execute_e2e_against_double_completes(
    whatsapp_test_env, cloud_api_double
):
    composed = _composed(cloud_api_double)
    result = await composed.runtime.execute(_send_payload())
    # When the SDK is fixed: the run completes and the dispatch result carries
    # a verifiable signed action envelope.
    assert result.taod_state.phase == "completed"
    assert result.dispatch_result is not None


async def test_runtime_execute_is_deterministic_across_two_runs(
    whatsapp_test_env, cloud_api_double
):
    """Two fresh runtimes given identical input produce agreeing receipts.

    ``assert_receipts_agree`` deep-compares the ordered audit chain (per-run
    run_id + wall-clock timestamps excluded). This demonstrates the intra-impl
    determinism the spec asks v0 to show. It holds regardless of the SDK
    execute() bug because both runs reach the SAME deterministic outcome (the
    double returns a stable wamid for an identical recipient).
    """
    payload = _send_payload()
    r1 = await _composed(cloud_api_double).runtime.execute(dict(payload))
    r2 = await _composed(cloud_api_double).runtime.execute(dict(payload))

    assert_receipts_agree(
        r1.to_dict(),
        r2.to_dict(),
        exclude_fields=frozenset({"run_id", "at"}),
    )


@requires_live_meta
async def test_live_meta_sandbox(whatsapp_test_env):
    """Tier-3 LIVE: send a real approved-template message via the Meta sandbox.

    Opt-in only — SKIPS with a "cannot execute" reason when no live
    ``WHATSAPP_*`` creds are present (journal 0003 Gap A). NEVER a mock
    fallback: absent creds, the test does not run. When it runs, it builds the
    REAL WhatsAppCloudApi from env (no injected client → a live httpx client
    against graph.facebook.com) and asserts a real wamid comes back.
    """
    import os

    recipient = os.environ["WHATSAPP_LIVE_E2E_RECIPIENT"]
    template = os.environ.get("WHATSAPP_LIVE_E2E_TEMPLATE", _APPROVED_TEMPLATE)

    # Real transport: no injected client, so each send opens a short-lived
    # httpx client against the live Meta Graph API.
    cloud_api = WhatsAppCloudApi.from_env()
    ingest = WebhookIngest.from_env()
    composed = build_whatsapp_runtime(
        cloud_api=cloud_api,
        ingest=ingest,
        sender_phone=_SENDER_PHONE,
        approved_templates=(template,),
    )

    from delegate_connectors.whatsapp.cloud_api import OutboundMessage

    message = OutboundMessage(to=recipient, template_name=template)

    async def send_thunk():
        result = await cloud_api.send(message)
        return {"wamid": result.wamid, "wa_id": result.wa_id, "to": message.to}

    envelope = await composed.connector.write(
        send_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )
    # A real Meta send returns a wamid; the audited envelope verifies.
    assert envelope.payload["wamid"].startswith("wamid.")
    assert verify_action_envelope(
        envelope,
        composed.verifier,
        observed_at=envelope.payload.get("observed_at", ""),
    ) or composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )
