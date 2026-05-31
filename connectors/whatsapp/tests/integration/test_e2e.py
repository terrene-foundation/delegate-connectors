# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-2/3 e2e: compose a DelegateRuntime and drive it against the Cloud API double.

The end-to-end ``runtime.execute()`` OUTCOME assertion (a COMPLETED run carrying
a verifiable dispatch result) now passes at kailash >= 2.28.1 — kailash-py#1182
(audit-emit signed the event payload bytes while AuditChainEngine verified the
full entry signing bytes) is fixed at <= 2.28.1. The xfail markers are removed.

The execute() tests use a freeform text payload ``{"to": ..., "text": "..."}``
(matching the WhatsAppV0Signature input_schema exactly: ``{"to": str, "text":
str}``). WhatsApp requires either an approved template OR an open 24h
customer-service window for freeform text; the window is pre-warmed via the
composed connector's ServiceWindowTracker so the TemplateGate is satisfied
without needing a template-name send or live infrastructure.

Intra-impl receipt determinism is asserted via ``assert_receipts_agree`` minus
the per-run-by-design fields (run_id, at, dispatch_id, audit_head_hash,
audit_chain_entries). Audit-chain integrity (round-trip + head-hash
re-validation) is covered by conformance vector DV-9; this test asserts the
outcome is deterministic (same phase, transition shape, dispatch result) for
identical input.

This is Tier-2 against the in-process protocol-faithful Cloud API double
(WA-ADR-5). The opt-in Tier-3 live Meta sandbox test lives below behind the
``requires_live_meta`` gate — it SKIPS with a "cannot execute" reason when no
live ``WHATSAPP_*`` creds are present (journal 0003 Gap A), never a mock.
"""

from __future__ import annotations

import json

import pytest

from kailash.delegate import assert_receipts_agree

from delegate_connectors.whatsapp.cloud_api import (
    WhatsAppCloudApi,
    WhatsAppCloudConfig,
)
from delegate_connectors.whatsapp.compose import build_whatsapp_runtime
from delegate_connectors.whatsapp.connector import verify_action_envelope
from delegate_connectors.whatsapp.redaction import normalize_e164
from delegate_connectors.whatsapp.webhook import WebhookIngest

from _live_meta import requires_live_meta

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_SENDER_PHONE = "+14155550000"
_RECIPIENT = "+14155551234"
_APPROVED_TEMPLATE = "order_update"


def _composed(cloud_api_double):
    """Build the real composed runtime over the in-process double.

    Pre-warms the service window for the recipient so a freeform text payload
    passes the TemplateGate without requiring an approved-template send.
    WhatsApp allows freeform text only within an open 24h customer-service
    window; the ServiceWindowTracker is injectable so this is deterministic and
    requires no real WhatsApp infrastructure. The freeform payload matches the
    WhatsAppV0Signature input_schema exactly (``{"to": str, "text": str}``),
    avoiding the DispatchValidationError that an extra ``template_name`` key
    would trigger (the dispatch surface uses a closed-world schema).
    """
    config = WhatsAppCloudConfig.from_env()
    cloud_api = WhatsAppCloudApi(config, client=cloud_api_double.client())
    ingest = WebhookIngest.from_env()
    composed = build_whatsapp_runtime(
        cloud_api=cloud_api,
        ingest=ingest,
        sender_phone=_SENDER_PHONE,
        approved_templates=(_APPROVED_TEMPLATE,),
    )
    # Pre-warm the 24h service window for the recipient so the freeform payload
    # passes the TemplateGate pre-flight check.
    recipient_normalized = normalize_e164(_RECIPIENT)
    composed.connector._template_gate._window.record_inbound(recipient_normalized)
    return composed


def _send_payload() -> dict[str, str]:
    """Freeform payload matching WhatsAppV0Signature input_schema exactly.

    Uses ``{"to": str, "text": str}`` — the closed-world schema the dispatch
    surface enforces. The service window for the recipient is pre-warmed in
    ``_composed()`` so the TemplateGate allows this freeform send.
    """
    return {
        "to": _RECIPIENT,
        "text": "hello",
    }


async def test_runtime_execute_e2e_against_double_completes(
    whatsapp_test_env, cloud_api_double
):
    """End-to-end run completes against the in-process double on kailash >= 2.28.1.

    Was strict-xfailed on kailash-py#1182 (audit-emit signed the event payload
    bytes while AuditChainEngine verified the full entry signing bytes;
    execute() failed at the first phase transition under any real verifier).
    Fixed at <= 2.28.1 (workspaces/whatsapp/journal/0008); the marker is
    removed and the run now completes carrying a dispatch result.

    The connector correctly rejects freeform text when the 24h customer-service
    window is not open (OutsideServiceWindowError). The service window is
    pre-warmed via the composed connector's ServiceWindowTracker in _composed()
    so the TemplateGate is satisfied without a template-name send.
    """
    composed = _composed(cloud_api_double)
    result = await composed.runtime.execute(_send_payload())
    assert result.taod_state.phase == "completed"
    assert result.dispatch_result is not None


async def test_runtime_execute_is_deterministic_across_two_runs(
    whatsapp_test_env, cloud_api_double
):
    """Two fresh runtimes given identical input produce agreeing receipts.

    ``assert_receipts_agree`` deep-compares the receipt tree minus the
    per-run-by-design fields: ``run_id`` + the per-transition ``at``
    timestamp, plus ``dispatch_id`` (a fresh UUID per dispatch),
    ``audit_head_hash`` and ``audit_chain_entries`` (SHA-256 hashes that
    incorporate ``dispatch_id`` and per-run audit state). Audit-chain
    integrity (round-trip + head-hash re-validation) is a distinct property
    covered by conformance vector DV-9-001; this test asserts the outcome is
    deterministic (same phase, transition shape, dispatch result) for
    identical input. Mirrors the slack connector's determinism test.
    """
    payload = _send_payload()
    r1 = await _composed(cloud_api_double).runtime.execute(dict(payload))
    r2 = await _composed(cloud_api_double).runtime.execute(dict(payload))

    assert_receipts_agree(
        r1.to_dict(),
        r2.to_dict(),
        exclude_fields=frozenset(
            {
                "run_id",
                "at",
                "dispatch_id",
                "audit_head_hash",
                "audit_chain_entries",
            }
        ),
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
    # observed_at is bound into canonical_bytes (NOT echoed in payload), so it
    # MUST be recovered from the signed bytes — mirrors slack's e2e idiom. The
    # prior `verify_action_envelope(..., observed_at=payload.get(...)) or
    # verifier.verify(...)` form was a false-green: payload.get returned "" so
    # the envelope-level check always failed and the `or` fallback masked it.
    assert envelope.payload["wamid"].startswith("wamid.")
    observed_at = json.loads(envelope.canonical_bytes.decode("utf-8"))["observed_at"]
    assert verify_action_envelope(envelope, composed.verifier, observed_at=observed_at)
