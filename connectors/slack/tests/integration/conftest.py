# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Integration-tier conftest.

Fixtures for the Tier-2 integration suite:

- ``slack_api_double`` — the in-process protocol-faithful Slack Web API double
  over a REAL ephemeral-port socket (ADR-S4). It is ALWAYS available, so the
  integration tests RUN in CI (they do NOT skip — the double IS the real-infra
  surrogate). Yields then closes the aiohttp runner/site (no unclosed sockets).
- ``composed_slack`` — a fully-wired real ``SlackConnector`` + identity /
  verifier / envelope bundle with the connector's REAL ``AsyncWebClient`` pointed
  at the double's base_url.

Credentials are set env-only via ``monkeypatch.setenv`` (``SLACK_BOT_TOKEN`` +
``SLACK_API_BASE_URL``) — never hardcoded into a connector body, never logged.

The integration directory is put on ``sys.path`` so the importable helper modules
(``_slack_api_double``, ``_live_slack``) resolve by name from the test modules — a
sibling ``conftest`` resolves to the nearest conftest on the path, not this file.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

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
async def slack_api_double():
    """The in-process Slack Web API double over a real ephemeral-port socket.

    Yields a STARTED double; closes the aiohttp runner/site on teardown so no
    socket/connector is left open (``rules/testing.md`` resource-cleanup).
    """
    double = SlackApiDouble()
    await double.start()
    try:
        yield double
    finally:
        await double.stop()


@pytest.fixture
def composed_slack(monkeypatch, slack_api_double):
    """A fully-wired real ``SlackConnector`` bundle pointed at the double.

    The transport is the REAL ``SlackTransport`` wrapping a REAL ``AsyncWebClient``
    whose base URL is the double's ephemeral-port address — so a fired post is a
    recorded request at the double, and the read path pulls real bytes back over
    the socket. Credentials are env-only via monkeypatch.
    """
    monkeypatch.setenv("SLACK_BOT_TOKEN", TEST_BOT_TOKEN)
    monkeypatch.setenv("SLACK_API_BASE_URL", slack_api_double.base_url)

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

    # REAL transport: SlackWebConfig.from_env() reads SLACK_BOT_TOKEN +
    # SLACK_API_BASE_URL (set above), and SlackTransport builds a REAL
    # AsyncWebClient pointed at the double — no _client injection.
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
        "transport": transport,
        "identity": identity,
        "verifier": verifier,
        "envelope": envelope,
        "delegate_id": delegate_id,
        "signing_key": sk,
        "double": slack_api_double,
    }
