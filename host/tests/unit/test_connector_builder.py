# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the compose-ceremony factory (P0-10a).

Contract under test
===================
- The factory composes a runnable ``DelegateRuntime`` from the spine-shipped
  concretes — structurally equivalent to the hand-rolled ``email/compose.py``
  ceremony (same concrete types wired), but built ONCE via the build-thunk shape.
- The composed runtime signs connector receipts via the host signer (P0-08b) over
  host-observed side effects (P0-08a) — NOT a connector-held key. The test
  connector holds only the host-owned verifier; it has no signing key at all.
- The factory references the verifier via the SINGLE canonical ``AuthVerifier``
  binding imported from ``trust_primitives`` (folds former P0-03) — the alias is
  imported AND used (``AuthVerifier(directory)``), never an orphan; and it
  resolves to the SDK ``Ed25519Verifier``.
- Receipts the host signs over factory-composed observations verify end-to-end
  under the composed verifier (both the write and read paths).
- The build-thunk contract is structurally enforced: a thunk returning a
  non-``Connector`` raises ``TypeError``; a thunk returning a connector built
  around its OWN (parallel) verifier — the forge oracle Phase 0 closes — raises
  ``ValueError``.

P0-10a builds + tests the factory; protocol-version negotiation is P0-10b and
wiring the reference connectors onto it is P0-09 / P0-11.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import (
    AuditChainEngine,
    DelegateRuntime,
    DispatchSurface,
    PrincipalDirectory,
)
from kailash.delegate.dispatch import (
    Connector,
    ConnectorInvocationResult,
)
from kailash.delegate.types import DelegateIdentity
from kailash.delegate.verifier import Ed25519Verifier

from delegate_connectors_host.connector_builder import (
    ComposedRuntime,
    connector_builder,
)
from delegate_connectors_host.dispatch_signing import HostSigner
from delegate_connectors_host.signing_bytes import (
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors_host.trust_primitives import AuthVerifier


# ── fixtures: a minimal real connector that holds NO key, only the verifier ───


@dataclass(frozen=True, slots=True)
class _StubSignature:
    """Minimal ``SignatureContract`` (name + input/output schema)."""

    name: str = "stub-do"
    input_schema: dict[str, type] | None = None
    output_schema: dict[str, type] | None = None

    def __post_init__(self) -> None:
        if self.input_schema is None:
            object.__setattr__(self, "input_schema", {"x": str})
        if self.output_schema is None:
            object.__setattr__(self, "output_schema", {"ok": bool})


class _StubConnector(Connector):
    """A real connector that authenticates against the HOST-owned verifier.

    Holds no signing key (no ``_signing_key`` attribute, no signer thunk) — the
    forge-closed shape P0-10a composes. ``invoke`` returns a real result so the
    connector is functional, not a stub.
    """

    connector_id = "delegate-connector-stub"
    connector_kind = "stub"
    requires_capabilities = frozenset({"stub.do"})

    def __init__(self, verifier: Ed25519Verifier) -> None:
        self._verifier = verifier

    @property
    def auth_verifier(self) -> Ed25519Verifier:
        return self._verifier

    async def invoke(
        self,
        input_payload: dict[str, Any],
        *,
        identity: DelegateIdentity,
        envelope: Any,
    ) -> ConnectorInvocationResult:
        return ConnectorInvocationResult(
            payload={"ok": True, **input_payload},
            audit_events=(),
            tenant_id_observed=None,
            external_side_effect=False,
        )


def _build_stub(verifier: Ed25519Verifier, tenant_id: str) -> _StubConnector:
    """A build-thunk that constructs the stub AROUND the host-owned verifier."""
    return _StubConnector(verifier)


def _transport(*, send_return=None, fetch_return=None):
    from delegate_connectors_host.bound_transport import BoundTransport

    async def send(*a, **k):
        return send_return

    async def fetch(*a, **k):
        return fetch_return

    return BoundTransport(send=send, fetch=fetch)


# ── composition: a runnable runtime equivalent to the hand-rolled compose ─────


def test_composes_runnable_runtime():
    composed = connector_builder(_build_stub, signature=_StubSignature())

    assert isinstance(composed, ComposedRuntime)
    # Same concrete types the hand-rolled email/compose.py wires.
    assert isinstance(composed.runtime, DelegateRuntime)
    assert isinstance(composed.dispatch_surface, DispatchSurface)
    assert isinstance(composed.audit_engine, AuditChainEngine)
    assert isinstance(composed.connector, _StubConnector)
    # The connector authenticates against the host-owned verifier (no parallel).
    assert composed.connector.auth_verifier is composed.verifier


def test_auth_verifier_is_the_canonical_sdk_binding():
    composed = connector_builder(_build_stub, signature=_StubSignature())

    # AuthVerifier is the single canonical binding, imported + used (not orphan),
    # and it resolves to the SDK Ed25519Verifier.
    assert AuthVerifier is Ed25519Verifier
    assert isinstance(composed.verifier, AuthVerifier)
    assert type(composed.verifier) is Ed25519Verifier


# ── signing: host signer over host-observed side effects, not a connector key ──


def test_connector_holds_no_signing_key():
    composed = connector_builder(_build_stub, signature=_StubSignature())

    # The composed signing surface is the host signer (P0-08b).
    assert isinstance(composed.host_signer, HostSigner)
    # The connector holds no key and no signer thunk — only the verifier.
    assert not hasattr(composed.connector, "_signing_key")
    assert not hasattr(composed.connector, "_sign")


async def test_signed_action_verifies_via_host_signer():
    sk = Ed25519PrivateKey.generate()
    composed = connector_builder(
        _build_stub, signature=_StubSignature(), signing_key=sk
    )
    transport = _transport(send_return={"accepted": True, "to": "ops@x.com"})

    observed = await composed.seam.observe_action(
        transport,
        lambda r: {"accepted": r["accepted"], "to": r["to"]},
        signer_delegate_id=str(composed.identity.delegate_id),
    )
    envelope = composed.host_signer.sign_action(observed)

    # raw-64-byte Ed25519 signature, and it verifies under the composed verifier
    assert isinstance(envelope.signature, bytes) and len(envelope.signature) == 64
    assert (
        verify_action_envelope(
            envelope, composed.verifier, observed_at=observed.observed_at
        )
        is True
    )


async def test_attested_read_verifies_via_host_signer():
    composed = connector_builder(_build_stub, signature=_StubSignature())
    transport = _transport(fetch_return=["m1", "m2"])

    observed = await composed.seam.observe_read(
        transport,
        lambda r: {"count": len(r), "message_ids": list(r)},
        attester_delegate_id=str(composed.identity.delegate_id),
    )
    value, receipt = composed.host_signer.attest_read(observed)

    assert value == ["m1", "m2"]
    assert isinstance(receipt.attestation, bytes) and len(receipt.attestation) == 64
    assert (
        verify_read_receipt(receipt, dict(observed.payload), composed.verifier) is True
    )


# ── build-thunk contract: structural rejections ───────────────────────────────


def test_rejects_non_connector_thunk():
    def _build_not_a_connector(verifier, tenant_id):
        return object()  # not a Connector

    with pytest.raises(TypeError, match="MUST return a Connector"):
        connector_builder(_build_not_a_connector, signature=_StubSignature())


def test_rejects_connector_with_parallel_verifier():
    def _build_parallel_verifier(verifier, tenant_id):
        # The forge oracle: connector builds its OWN verifier instead of using
        # the host-owned one it was handed.
        sk = Ed25519PrivateKey.generate()
        did = uuid.uuid4()
        directory = PrincipalDirectory(
            identities=(
                DelegateIdentity(
                    delegate_id=did,
                    sovereign_ref="s",
                    role_binding_ref="r",
                    genesis_ref="g",
                ),
            ),
            verification_keys={did: sk.public_key().public_bytes_raw()},
        )
        return _StubConnector(Ed25519Verifier(directory))

    with pytest.raises(ValueError, match="host-owned verifier"):
        connector_builder(_build_parallel_verifier, signature=_StubSignature())
