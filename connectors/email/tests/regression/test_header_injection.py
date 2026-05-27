# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression — H1 (HIGH): SMTP header injection via CR/LF/NUL.

Before this fix, `connector.invoke` built an `OutboundMessage` from
`input_payload` and `smtp.to_mime` assigned `sender`/`to`/`subject` straight to
MIME headers with NO validation. A `to`/`subject`/`sender` carrying `\\r`,
`\\n`, or `\\x00` injected additional headers (e.g. a blind `Bcc:` for silent
exfiltration) or split the message.

Fix: every header-bound field is validated at the `OutboundMessage`
construction boundary (`__post_init__` → `validate_header_field`), raising the
typed `HeaderInjectionError` BEFORE any MIME message is built or any byte
transits SMTP. Because every send route constructs an `OutboundMessage` first
(the dispatch `invoke` hot path AND any direct `write`/`to_mime` call), the
single boundary covers all of them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import DelegateIdentity, Ed25519Verifier, PrincipalDirectory
from kailash.delegate.dispatch import Principal
from kailash.delegate.envelope import DelegateConstraintEnvelope
from kailash.delegate.types import DelegateGenesisRecord
from kailash.trust.chain import AuthorityType, GenesisRecord
from kailash.trust.envelope import ConstraintEnvelope

from delegate_connectors.email.connector import EmailConnector
from delegate_connectors.email.directory import EmailPrincipalResolver
from delegate_connectors.email.imap import ImapConfig, ImapTransport
from delegate_connectors.email.smtp import (
    HeaderInjectionError,
    OutboundMessage,
    SmtpConfig,
    SmtpTransport,
    validate_header_field,
)

pytestmark = pytest.mark.regression


# ── Tier-1: validator + construction boundary ───────────────────────────────


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("to", "a@x.com\r\nBcc: evil@x.com"),
        ("to", "a@x.com\nBcc: evil@x.com"),
        ("subject", "hi\r\nBcc: evil@x.com"),
        ("subject", "hi\nX-Injected: 1"),
        ("sender", "a@x.com\r\nFrom: spoof@x.com"),
        ("to", "a@x.com\x00bob@x.com"),
        ("subject", "vt\x0bhere"),
    ],
)
def test_validate_header_field_rejects_crlf_nul_and_control(field_name, value):
    with pytest.raises(HeaderInjectionError):
        validate_header_field(field_name, value)


def test_validate_header_field_passes_clean_value():
    assert validate_header_field("to", "bob@x.com") == "bob@x.com"
    assert validate_header_field("subject", "Quarterly report") == "Quarterly report"


def test_outbound_message_rejects_crlf_in_recipient():
    with pytest.raises(HeaderInjectionError):
        OutboundMessage(
            sender="alice@x.com",
            recipient="bob@x.com\r\nBcc: evil@x.com",
            subject="Hi",
            body="body",
        )


def test_outbound_message_rejects_crlf_in_subject():
    with pytest.raises(HeaderInjectionError):
        OutboundMessage(
            sender="alice@x.com",
            recipient="bob@x.com",
            subject="Hi\r\nBcc: evil@x.com",
            body="body",
        )


def test_outbound_message_rejects_crlf_in_sender():
    with pytest.raises(HeaderInjectionError):
        OutboundMessage(
            sender="alice@x.com\r\nFrom: spoof@x.com",
            recipient="bob@x.com",
            subject="Hi",
            body="body",
        )


# ── invoke path: typed error raised AND zero SMTP send ───────────────────────


@pytest.fixture
def connector_fixture():
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
    resolver = EmailPrincipalResolver(
        {
            "alice@example.com": Principal(
                delegate_id=str(delegate_id), tenant_id="t1", claims={}
            )
        }
    )
    connector = EmailConnector(
        smtp=SmtpTransport(SmtpConfig(host="h", port=1025)),
        imap=ImapTransport(ImapConfig(host="h", port=1143)),
        resolver=resolver,
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
        block=genesis_block, spec_version="0", capabilities=("email.send",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)
    return {"connector": connector, "identity": identity, "envelope": envelope}


@pytest.mark.parametrize(
    "payload",
    [
        {
            "sender": "alice@example.com",
            "to": "bob@x.com\r\nBcc: evil@x.com",
            "subject": "Hi",
            "body": "yo",
        },
        {
            "sender": "alice@example.com",
            "to": "bob@x.com",
            "subject": "Hi\r\nBcc: evil@x.com",
            "body": "yo",
        },
    ],
)
@pytest.mark.asyncio
async def test_invoke_rejects_header_injection_and_does_not_send(
    connector_fixture, monkeypatch, payload
):
    """A crafted to/subject raises HeaderInjectionError and ZERO SMTP send fires."""
    conn = connector_fixture["connector"]
    sends: list = []

    async def recording_send(message):  # pragma: no cover - must NOT be called
        sends.append(message)
        raise AssertionError("SMTP send MUST NOT fire on header-injection input")

    monkeypatch.setattr(conn._smtp, "send", recording_send)

    with pytest.raises(HeaderInjectionError):
        await conn.invoke(
            payload,
            identity=connector_fixture["identity"],
            envelope=connector_fixture["envelope"],
        )
    assert sends == [], "no SMTP send may occur when the header field is malicious"
