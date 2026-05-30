# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures for the Slack security regression suite.

Builds a REAL ``SlackConnector`` — the real ``kailash.delegate.dispatch.Connector``
subclass, a real Ed25519 signing key + shipped ``Ed25519Verifier``, a real
``SlackTransport`` (wrapping a REAL ``slack_sdk`` ``AsyncWebClient``) whose HTTP
byte stream terminates at the in-process ``SlackApiDouble`` over a REAL
ephemeral-port socket (NO mock of the connector / Web API client; the double is a
Protocol-satisfying deterministic adapter per ``rules/testing.md`` § "Protocol
Adapters" + ADR-S4).

The connector contract is never stubbed: the only external boundary is the aiohttp
socket, terminated by the in-process double. A fired ``chat.postMessage`` is a
recorded post at the double; ZERO recorded posts proves no send occurred — the
behavioral signal the Reject-gate regressions assert on.

Credentials come from ``monkeypatch.setenv`` (``SLACK_BOT_TOKEN`` +
``SLACK_API_BASE_URL`` pointed at the double) — never hardcoded beyond the
deterministic non-secret test fixtures here.

The integration helper directory is put on ``sys.path`` so ``_slack_api_double``
is importable by name (ONE double definition shared across tiers — no per-tier
fork).
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# The in-process double lives in the integration helper module; reuse it so the
# regression suite shares ONE double definition (no per-tier fork).
_INTEGRATION_DIR = Path(__file__).parent.parent / "integration"
if str(_INTEGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_DIR))

from _slack_api_double import (  # noqa: E402
    CHANNEL_ID,
    SENDER_SLACK_ID,
    TEST_BOT_TOKEN,
    SlackApiDouble,
)

from kailash.delegate import (  # noqa: E402
    DelegateIdentity,
    Ed25519Verifier,
    PrincipalDirectory,
)
from kailash.delegate.dispatch import Principal  # noqa: E402
from kailash.delegate.envelope import DelegateConstraintEnvelope  # noqa: E402
from kailash.delegate.types import DelegateGenesisRecord  # noqa: E402
from kailash.trust.chain import AuthorityType, GenesisRecord  # noqa: E402
from kailash.trust.envelope import ConstraintEnvelope  # noqa: E402

from delegate_connectors.slack.connector import SlackConnector  # noqa: E402
from delegate_connectors.slack.directory import SlackPrincipalResolver  # noqa: E402
from delegate_connectors.slack.web_api import (  # noqa: E402
    SlackTransport,
    SlackWebConfig,
)

__all__ = ["CHANNEL_ID", "SENDER_SLACK_ID", "TEST_BOT_TOKEN"]


@pytest_asyncio.fixture
async def double():
    """The in-process Slack Web API double over a real ephemeral-port socket.

    Used as a transport call-spy: every ``chat.postMessage`` the REAL production
    transport emits is recorded on ``.posts``; a Reject-gate test asserts
    ``.posts == []`` to prove no send fired. Closed on teardown.
    """
    d = SlackApiDouble()
    await d.start()
    try:
        yield d
    finally:
        await d.stop()


@pytest.fixture
def slack(monkeypatch, double):
    """A fully-wired SlackConnector + identity/verifier/envelope bundle.

    The connector's transport is the REAL ``SlackTransport`` over a REAL
    ``AsyncWebClient`` whose byte stream terminates at ``double`` — so a fired post
    is a recorded post, and zero recorded posts proves no send occurred.
    """
    monkeypatch.setenv("SLACK_BOT_TOKEN", TEST_BOT_TOKEN)
    monkeypatch.setenv("SLACK_API_BASE_URL", double.base_url)

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
        claims={"slack_user_id": SENDER_SLACK_ID},
    )
    resolver = SlackPrincipalResolver({SENDER_SLACK_ID: principal})

    transport = SlackTransport(SlackWebConfig.from_env())
    connector = SlackConnector(
        transport=transport,
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
        block=genesis_block, spec_version="0", capabilities=("slack.post",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)

    return {
        "connector": connector,
        "identity": identity,
        "verifier": verifier,
        "envelope": envelope,
        "delegate_id": delegate_id,
        "signing_key": sk,
        "double": double,
    }
