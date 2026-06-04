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
    HOST_SUPPORTED_PROTOCOLS,
    ComposedRuntime,
    HostSigningSurface,
    ProtocolUnsupportedError,
    connector_builder,
)
from delegate_connectors_host.dispatch_observation import DispatchObservationSeam
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


def _build_stub(
    verifier: Ed25519Verifier, tenant_id: str, *, host_signing=None
) -> _StubConnector:
    """A build-thunk that constructs the stub AROUND the host-owned verifier.

    The stub does not route side effects through ``host_signing`` (it is a
    minimal Connector exercising the factory contract, not the host-owned
    invocation path — that is covered by the per-connector wiring tests).
    """
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


def test_factory_passes_host_signing_surface_to_thunk():
    # P0-09 contract: the factory builds the seam + host signer and hands the
    # build-thunk a HostSigningSurface (so the connector can route side effects
    # through the host without holding a key).
    captured = {}

    def _capturing_thunk(verifier, tenant_id, *, host_signing):
        captured["host_signing"] = host_signing
        return _StubConnector(verifier)

    composed = connector_builder(_capturing_thunk, signature=_StubSignature())
    hs = captured["host_signing"]
    assert isinstance(hs, HostSigningSurface)
    assert isinstance(hs.seam, DispatchObservationSeam)
    assert isinstance(hs.host_signer, HostSigner)
    # The surface handed to the connector is the SAME one exposed on the runtime.
    assert hs.seam is composed.seam
    assert hs.host_signer is composed.host_signer


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
    def _build_not_a_connector(verifier, tenant_id, **_):
        return object()  # not a Connector

    with pytest.raises(TypeError, match="MUST return a Connector"):
        connector_builder(_build_not_a_connector, signature=_StubSignature())


def test_rejects_connector_with_parallel_verifier():
    def _build_parallel_verifier(verifier, tenant_id, **_):
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


# ── host-protocol negotiation gate (P0-10b) ───────────────────────────────────


def _connector_at(protocol):
    """A build-thunk for a stub connector declaring ``delegate_host_protocol``.

    ``protocol=None`` declares NOTHING (exercises the default).
    """

    class _ProtoConnector(_StubConnector):
        if protocol is not None:
            delegate_host_protocol = protocol

    return lambda verifier, tenant_id, **_: _ProtoConnector(verifier)


def test_default_non_declaring_connector_binds_at_v1():
    # The four v0 connectors declare no delegate_host_protocol -> default {1}.
    composed = connector_builder(_build_stub, signature=_StubSignature())
    assert composed.bound_protocol == 1


def test_declared_int_in_host_set_loads_and_binds():
    composed = connector_builder(_connector_at(1), signature=_StubSignature())
    assert composed.bound_protocol == 1


def test_declared_range_overlapping_binds_at_max_of_intersection():
    # Connector speaks {1,2}; host speaks {1}; S ∩ H = {1}; bind at max = 1.
    composed = connector_builder(_connector_at([1, 2]), signature=_StubSignature())
    assert composed.bound_protocol == 1
    assert composed.bound_protocol == max({1, 2} & HOST_SUPPORTED_PROTOCOLS)


def test_disjoint_int_refuses_loudly_with_portable_kind():
    # Connector requires v2; host only speaks v1; S ∩ H = ∅ -> loud load-time refusal.
    with pytest.raises(ProtocolUnsupportedError) as exc:
        connector_builder(_connector_at(2), signature=_StubSignature())
    err = exc.value
    # Portable, language-neutral identity — NOT the Python class name (§9).
    assert err.kind == "protocol.unsupported"
    # Message names connector kind + connector's declared value + host's set (§8).
    msg = str(err)
    assert "stub" in msg  # connector kind
    assert "delegate_host_protocol 2 " in msg  # connector's declared value
    assert str(sorted(HOST_SUPPORTED_PROTOCOLS)) in msg  # host's set


def test_disjoint_range_refuses_naming_declared_range_not_expanded():
    with pytest.raises(ProtocolUnsupportedError) as exc:
        connector_builder(_connector_at([2, 4]), signature=_StubSignature())
    err = exc.value
    assert err.kind == "protocol.unsupported"
    # §8: name the connector's DECLARED RANGE — the compact "[2, 4]", NOT the
    # expanded set "[2, 3, 4]" (which would also diverge from a Rust impl's form).
    assert "[2, 4]" in str(err)
    assert "[2, 3, 4]" not in str(err)


def test_protocol_unsupported_is_a_valueerror():
    # Subclasses ValueError so a generic load-error handler still catches it.
    assert issubclass(ProtocolUnsupportedError, ValueError)


def test_malformed_declaration_is_valueerror_not_protocol_unsupported():
    # A malformed declaration is a connector bug, distinct from S ∩ H = ∅:
    # it raises plain ValueError WITHOUT the protocol.unsupported kind.
    for bad in ([3, 1], "1", {"min": 1}, [1, 2, 3], True, [1, True]):
        with pytest.raises(ValueError) as exc:
            connector_builder(_connector_at(bad), signature=_StubSignature())
        assert not isinstance(exc.value, ProtocolUnsupportedError), bad


def test_protocol_axis_independent_of_sdk_pin(monkeypatch):
    # delegate_host_protocol is the cross-impl wire-contract axis; the kailash
    # dependency pin is a DIFFERENT axis. Prove the gate's DECISION never reads
    # the SDK version: monkeypatch kailash.__version__ to an arbitrary value and
    # assert the negotiated bound_protocol is unchanged.
    import kailash

    baseline = connector_builder(_connector_at(1), signature=_StubSignature())
    assert baseline.bound_protocol == 1

    monkeypatch.setattr(kailash, "__version__", "999.999.999", raising=False)
    after = connector_builder(_connector_at(1), signature=_StubSignature())
    assert after.bound_protocol == 1  # decision invariant under SDK version change

    # Structural backstop: the negotiation source never references the SDK version.
    import importlib
    import inspect

    cb = importlib.import_module("delegate_connectors_host.connector_builder")
    src = inspect.getsource(cb._negotiate_protocol) + inspect.getsource(
        cb._declared_bounds
    )
    assert "__version__" not in src


def test_max_binding_picks_highest_common_under_widened_host(monkeypatch):
    # With H={1} today every S ∩ H is {1}, so "binds at MAX" is unprovable. Widen
    # the host to {1,2,3} and prove the gate picks the HIGHEST common version
    # (max), not the lowest — a min()-binding would fail these.
    import importlib

    cb = importlib.import_module("delegate_connectors_host.connector_builder")
    monkeypatch.setattr(cb, "HOST_SUPPORTED_PROTOCOLS", frozenset({1, 2, 3}))

    assert (
        connector_builder(_connector_at([1, 3]), signature=_StubSignature())
    ).bound_protocol == 3  # S∩H={1,2,3} -> max 3, not min 1
    assert (
        connector_builder(_connector_at([2, 2]), signature=_StubSignature())
    ).bound_protocol == 2
    assert (
        connector_builder(_connector_at([3, 9]), signature=_StubSignature())
    ).bound_protocol == 3  # S∩H={3}
    # Above-host range still refuses.
    with pytest.raises(ProtocolUnsupportedError):
        connector_builder(_connector_at([4, 9]), signature=_StubSignature())


def test_refusal_fires_before_any_runtime_composition(monkeypatch):
    # Invariant 2: the refusal is LOAD-TIME — raised BEFORE any composition object
    # is constructed. A future refactor moving the gate below composition would
    # leak a partially-composed runtime + register the cascade grantee; this test
    # pins the ordering so that refactor fails loudly.
    from kailash.delegate import DelegateRuntime, DispatchSurface
    from kailash.delegate.trust import TenantScopedCascade

    built: list[str] = []
    real_rt, real_ds = DelegateRuntime.__init__, DispatchSurface.__init__
    real_grant = TenantScopedCascade.register_root_grantee

    def _rt(self, *a, **k):
        built.append("DelegateRuntime")
        return real_rt(self, *a, **k)

    def _ds(self, *a, **k):
        built.append("DispatchSurface")
        return real_ds(self, *a, **k)

    def _grant(self, *a, **k):
        built.append("register_root_grantee")
        return real_grant(self, *a, **k)

    monkeypatch.setattr(DelegateRuntime, "__init__", _rt)
    monkeypatch.setattr(DispatchSurface, "__init__", _ds)
    monkeypatch.setattr(TenantScopedCascade, "register_root_grantee", _grant)

    with pytest.raises(ProtocolUnsupportedError):
        connector_builder(_connector_at(2), signature=_StubSignature())
    assert built == []  # nothing composed before the load-time refusal


def test_huge_range_declaration_does_not_oom():
    # A well-formed but enormous range is a valid integer pair; the gate MUST NOT
    # materialize range(lo, hi+1) (which would OOM the host at load time). With
    # H={1}, [1, 2**53-1] contains 1 -> loads at v1, instantly.
    composed = connector_builder(
        _connector_at([1, 2**53 - 1]), signature=_StubSignature()
    )
    assert composed.bound_protocol == 1
    # An enormous range that EXCLUDES the host set still refuses fast (no materialize).
    with pytest.raises(ProtocolUnsupportedError):
        connector_builder(_connector_at([2, 2**53 - 1]), signature=_StubSignature())
