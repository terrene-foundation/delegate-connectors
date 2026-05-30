# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-2 integration: real connector round-trips against the Cloud API double.

NO mocks at the boundary. The REAL
:class:`~delegate_connectors.whatsapp.cloud_api.WhatsAppCloudApi` transport runs
over a REAL :class:`httpx.AsyncClient` whose byte stream terminates at the
in-process protocol-faithful Meta Cloud API double (WA-ADR-5). Real in-memory
audit ledger, real :class:`~kailash.delegate.verifier.Ed25519Verifier`.

Two round-trips:

- **Send**: drive the connector ``write`` path with a thunk that POSTs through
  the real transport. Assert (a) the request the double received matches the
  Meta ``POST /messages`` contract (URL shape, Bearer auth, JSON body), and (b)
  the :class:`SendResult` + the signed envelope carry the ``wamid`` + ``wa_id``,
  with the envelope verifying under the composed real verifier.
- **Inbound**: inject a signed inbound webhook → buffer → connector ``read``
  path → assert a verifiable :class:`AttestedReadReceipt`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest

from delegate_connectors.whatsapp.cloud_api import (
    OutboundMessage,
    RateLimitedError,
    WhatsAppCloudApi,
    WhatsAppCloudConfig,
)
from delegate_connectors.whatsapp.compose import build_whatsapp_runtime
from delegate_connectors.whatsapp.connector import verify_read_receipt
from delegate_connectors.whatsapp.webhook import WebhookIngest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_SENDER_PHONE = "+14155550000"
_RECIPIENT = "+14155551234"


def _composed(whatsapp_test_env, cloud_api_double):
    """Build the real composed runtime with the transport pointed at the double."""
    config = WhatsAppCloudConfig.from_env()
    cloud_api = WhatsAppCloudApi(config, client=cloud_api_double.client())
    ingest = WebhookIngest.from_env()
    return (
        build_whatsapp_runtime(
            cloud_api=cloud_api,
            ingest=ingest,
            sender_phone=_SENDER_PHONE,
        ),
        ingest,
        cloud_api,
    )


def _signed_inbound(
    ingest: WebhookIngest, *, sender: str, text: str
) -> tuple[bytes, str]:
    """Build a webhook payload signed exactly as Meta would sign the raw body.

    Uses the SAME app secret the ingest verifies against (from the env-only
    startup config), so the signature passes the connector's REAL HMAC boundary
    — no bypass of ``verify_signature``.
    """
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": sender,
                                    "id": "wamid.INBOUND" + uuid.uuid4().hex[:8],
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode("utf-8")
    secret = ingest.config.app_secret.encode("utf-8")
    sig = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return raw, sig


async def test_send_path_matches_meta_messages_contract_and_carries_wamid(
    whatsapp_test_env, cloud_api_double
):
    """The audited write path POSTs the Meta /messages shape and returns wamid+wa_id."""
    composed, _ingest, cloud_api = _composed(whatsapp_test_env, cloud_api_double)
    config = cloud_api.config

    message = OutboundMessage(to=_RECIPIENT, text="hello over the double")

    captured: dict[str, object] = {}

    async def send_thunk():
        result = await cloud_api.send(message)
        captured["result"] = result
        return {"wamid": result.wamid, "wa_id": result.wa_id, "to": message.to}

    # Audited write — the Cloud API POST is the external side effect.
    envelope = await composed.connector.write(
        send_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    # 1. The request the double received matches the Meta POST /messages contract.
    req = cloud_api_double.last_request
    assert req.method == "POST"
    expected_url = (
        f"https://graph.facebook.com/v{config.graph_version}/"
        f"{config.phone_number_id}/messages"
    )
    assert req.url == expected_url
    assert req.headers["authorization"] == f"Bearer {config.access_token}"
    assert req.headers["content-type"] == "application/json"
    assert req.json_body["messaging_product"] == "whatsapp"
    assert req.json_body["type"] == "text"
    assert req.json_body["text"]["body"] == "hello over the double"
    # Recipient is the bare-digit E.164 normalized form (the leading + stripped).
    assert req.json_body["to"] == "14155551234"

    # 2. SendResult carries the wamid + wa_id the double reported.
    send_result = captured["result"]
    assert send_result.wamid.startswith("wamid.")
    assert send_result.wa_id == "14155551234"

    # 3. The signed envelope is non-empty, carries the wamid (non-PII), and
    #    verifies under the composed REAL Ed25519Verifier. The recipient `to`
    #    and `wa_id` are PII-redacted in the audited payload (binding floor).
    assert envelope.signature and envelope.canonical_bytes
    assert envelope.payload["wamid"] == send_result.wamid
    assert envelope.payload["to"].startswith("wa:")  # redacted, not raw E.164
    assert envelope.payload["wa_id"].startswith("wa:")
    assert composed.verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        str(composed.identity.delegate_id),
    )


async def test_write_raises_and_signs_nothing_when_cloud_api_rejects(
    whatsapp_test_env, cloud_api_double
):
    """A Cloud API rejection MUST raise OUT of write() — no envelope is signed.

    Drives the connector ``write`` path end-to-end through the real transport
    against a double forced to return the Meta 429 envelope. The transport
    raises :class:`RateLimitedError`; the raise propagates out of ``write`` so
    NO :class:`SignedActionEnvelope` is produced. Connector-level expression of
    the sign-only-on-success invariant — closes the Tier-1→Tier-2 gap (the
    double advertised ``force_status`` but no integration test exercised it).
    """
    composed, _ingest, cloud_api = _composed(whatsapp_test_env, cloud_api_double)
    cloud_api_double.force_status = 429

    message = OutboundMessage(to=_RECIPIENT, text="rejected send")

    async def send_thunk():
        result = await cloud_api.send(message)
        return {"wamid": result.wamid, "wa_id": result.wa_id, "to": message.to}

    with pytest.raises(RateLimitedError):
        await composed.connector.write(
            send_thunk,
            identity=composed.identity,
            envelope=composed.dispatch_surface.envelope,
        )


async def test_inbound_signed_webhook_round_trips_through_read(
    whatsapp_test_env, cloud_api_double
):
    """Signed webhook → buffer → connector read → verifiable AttestedReadReceipt."""
    composed, ingest, _cloud_api = _composed(whatsapp_test_env, cloud_api_double)

    raw, sig = _signed_inbound(ingest, sender="14155559999", text="inbound hello")
    buffered = ingest.ingest(raw, sig)
    assert (
        buffered == 1
    ), "signed inbound MUST verify + buffer through the real HMAC gate"

    async def drain_thunk():
        return ingest.drain_all()

    messages, receipt = await composed.connector.read(
        drain_thunk,
        identity=composed.identity,
        envelope=composed.dispatch_surface.envelope,
    )

    assert len(messages) == 1
    assert messages[0].text == "inbound hello"
    # Sender is stored ONLY as the redacted token (M1 contract) — never raw.
    assert messages[0].sender_redacted.startswith("wa:")

    # The attestation is non-empty and the full identity-bound receipt verifies:
    # the manifest re-derived from the drained messages matches the signed bytes.
    assert receipt.attestation and receipt.canonical_bytes
    assert composed.verifier.verify(
        receipt.canonical_bytes,
        receipt.attestation,
        str(composed.identity.delegate_id),
    )
    manifest = {
        "count": len(messages),
        "message_ids": [m.message_id for m in messages],
    }
    assert verify_read_receipt(receipt, manifest, composed.verifier) is True


async def test_unsigned_inbound_webhook_is_refused_at_the_boundary(
    whatsapp_test_env, cloud_api_double
):
    """An invalid signature is REFUSED — never buffered, never read."""
    composed, ingest, _cloud_api = _composed(whatsapp_test_env, cloud_api_double)

    raw, _sig = _signed_inbound(ingest, sender="14155559999", text="forged")
    # Wrong signature → the real verify_signature boundary refuses it.
    refused = ingest.ingest(raw, "sha256=" + "0" * 64)
    assert refused == 0
    assert ingest.buffered_count == 0
