# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — binding security property 1: PII redaction.

Every ``SignedActionEnvelope`` / ``AttestedReadReceipt`` canonical-bytes payload
AND every ``InMemoryKnowledgeLedger`` record MUST carry the ``wa:``-token, NEVER
the raw E.164. These tests assert behaviorally: drive the REAL ``write`` / ``read``
/ ``invoke`` paths, then SEARCH the serialized artifacts (canonical bytes, payload
JSON, ledger records) for the raw digits — they MUST be absent. A redaction
failure surfaces the ``<unredactable wa identity>`` sentinel, never the raw number.

Invariant 1: raw phone / ``wa_id`` absent from every audit-bytes / ledger surface.
"""

from __future__ import annotations

import json

import pytest

from delegate_connectors.whatsapp.redaction import (
    REDACTION_SENTINEL,
    RedactionConfig,
    redact_phone,
)
from delegate_connectors.whatsapp.webhook import InboundMessage

from .conftest import SENDER_PHONE

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]

# P0-07: the connector's startup gate validates this key (the conftest `wa`
# fixture sets it in the env before construction). Tests that drive
# redact_phone directly thread the SAME key the connector validated.
_PII_KEY = "test-pii-hmac-key-min-len"


def _ledger_blob(connector) -> str:
    """Serialize every ledger record to a single searchable string."""
    return json.dumps([list(rec) for rec in connector.ledger.records], default=str)


async def test_write_envelope_carries_token_never_raw_number(wa):
    """write: raw E.164 absent from canonical bytes + payload; token present."""
    conn, identity = wa["connector"], wa["identity"]

    async def thunk():
        # The write-action result mirrors a Cloud API send: PII-bearing fields.
        return {"wamid": "wamid.X", "wa_id": SENDER_PHONE, "to": SENDER_PHONE}

    envelope = await conn.write(thunk, identity=identity, envelope=wa["envelope"])

    canonical = envelope.canonical_bytes.decode("utf-8")
    payload_blob = json.dumps(envelope.payload)

    # The raw digits MUST be absent from the signed bytes AND the payload.
    assert SENDER_PHONE not in canonical
    assert SENDER_PHONE not in payload_blob
    # The redacted token IS present, on every PII-bearing field.
    assert envelope.payload["wa_id"].startswith("wa:")
    assert envelope.payload["to"].startswith("wa:")
    # The sentinel must NOT appear — redaction succeeded with a real key.
    assert REDACTION_SENTINEL not in canonical


async def test_ledger_record_carries_token_never_raw_number(wa):
    """The ledger record written on a write carries the token, never the raw E.164."""
    conn, identity = wa["connector"], wa["identity"]

    async def thunk():
        return {"wamid": "wamid.X", "wa_id": SENDER_PHONE, "to": SENDER_PHONE}

    await conn.write(thunk, identity=identity, envelope=wa["envelope"])

    blob = _ledger_blob(conn)
    assert conn.ledger.records, "a write MUST append a ledger record"
    assert SENDER_PHONE not in blob
    assert "wa:" in blob


async def test_invoke_audit_surfaces_carry_token_never_raw_number(wa):
    """invoke (real transport spy): the audited side-effect leaks no raw number."""
    conn, identity, spy = wa["connector"], wa["identity"], wa["transport_spy"]

    result = await conn.invoke(
        {"to": SENDER_PHONE, "text": "yo"},
        identity=identity,
        envelope=wa["envelope"],
    )

    # The send fired against the real transport spy (proves we drove the real path).
    assert len(spy.requests) == 1
    # The result payload + the ledger record carry the token, never the raw number.
    result_blob = json.dumps(result.payload)
    assert SENDER_PHONE not in result_blob
    assert result.payload["to"].startswith("wa:")
    assert SENDER_PHONE not in _ledger_blob(conn)


async def test_read_receipt_omits_sender_wa_id(wa):
    """read: the signed manifest carries only ids + count — never a sender wa_id."""
    conn, identity, verifier = wa["connector"], wa["identity"], wa["verifier"]

    async def thunk():
        return [
            InboundMessage(
                # P0-07: thread the same startup key the connector validated.
                sender_redacted=redact_phone(SENDER_PHONE, hmac_key=_PII_KEY),
                message_type="text",
                text="hello",
                timestamp="1700000000",
                message_id="wamid.M1",
            )
        ]

    messages, receipt = await conn.read(
        thunk, identity=identity, envelope=wa["envelope"]
    )

    canonical = receipt.canonical_bytes.decode("utf-8")
    # Neither the raw sender number nor the body enters the signed manifest.
    assert SENDER_PHONE not in canonical
    assert "hello" not in canonical
    # The receipt still verifies under the real verifier (real signed bytes).
    manifest = {"count": 1, "message_ids": ["wamid.M1"]}
    from delegate_connectors.whatsapp.connector import verify_read_receipt

    assert verify_read_receipt(receipt, manifest, verifier) is True
    assert _ledger_blob(conn).count(SENDER_PHONE) == 0


async def test_redaction_failure_surfaces_sentinel_never_raw_number(wa):
    """On a transient redaction failure, the audit payload carries the sentinel.

    Simulate the runtime-soft half of the dual contract: a per-message redaction
    failure (e.g. a transient unusable key at one call site) MUST collapse to the
    grep-able sentinel in the audit payload — NEVER the raw number, NEVER a raise.

    P0-07: the key is now THREADED from the connector's startup-validated
    ``RedactionConfig`` rather than re-read from os.environ per message. The
    transient-glitch state is therefore modeled by replacing the connector's
    held config with an empty-key config (a rotated-to-unusable key) — the
    faithful equivalent of the old "delete the env-var after construction"
    scenario, now expressed where the key actually lives.
    """
    conn, identity = wa["connector"], wa["identity"]

    # Simulate the transient glitch: the held key became unusable (empty).
    # redact_phone is fail-soft on an absent/empty key — it returns the
    # sentinel, never the raw value.
    conn._redaction_config = RedactionConfig(hmac_key="")
    # Sanity: redacting under the unusable key yields the sentinel, not raw.
    assert redact_phone(SENDER_PHONE, hmac_key="") == REDACTION_SENTINEL

    async def thunk():
        return {"wamid": "wamid.X", "wa_id": SENDER_PHONE, "to": SENDER_PHONE}

    envelope = await conn.write(thunk, identity=identity, envelope=wa["envelope"])
    canonical = envelope.canonical_bytes.decode("utf-8")

    # The raw number is STILL absent; the sentinel stands in its place.
    assert SENDER_PHONE not in canonical
    assert envelope.payload["to"] == REDACTION_SENTINEL
    assert envelope.payload["wa_id"] == REDACTION_SENTINEL
