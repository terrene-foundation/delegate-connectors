# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""The versioned compose-ceremony factory (Phase-0, P0-10a).

``connector_builder`` absorbs the ~250-LOC compose ceremony every connector
hand-copies today (246 LOC ``email/compose.py`` / 286 LOC ``whatsapp``). It
performs the ceremony ONCE — ``PrincipalDirectory`` + the canonical
``AuthVerifier`` + ``GenesisRecord`` + ``TrustLineageChain`` + ``AuditChainEngine``
+ ``TenantScopedCascade`` (root grantee registered with a real Ed25519 grant
proof) + ``Role`` + ``DispatchSurface`` + ``DelegateRuntime`` — using the
spine-shipped concretes for everything except the connector.

Build-thunk shape (why the connector is built INSIDE the factory)
=================================================================
The host owns the key→directory→verifier provenance: for a host-signed receipt
to verify, the host key's public half MUST be the one registered in the
verifier's directory, and that directory MUST be the verifier the connector
authenticates against. A factory that took a *finished* connector instance would
force the connector to build its own verifier and hold its own key — which IS
the **forge oracle** architecture §3.5 layer 2(b) names (a connector that signs a
side effect the host never brokered). So the factory mints the trust core FIRST
(``signing_key`` → ``PrincipalDirectory`` → ``AuthVerifier`` → seam →
``HostSigner``), then calls the caller-supplied ``build_connector(verifier,
tenant_id)`` thunk to construct the connector AROUND the host-owned verifier. The
factory then asserts ``connector.auth_verifier is verifier`` — the connector
cannot smuggle in a parallel verifier.

The canonical ``AuthVerifier`` binding
======================================
The verifier is constructed via :data:`AuthVerifier` imported from
:mod:`delegate_connectors_host.trust_primitives` — the SINGLE canonical host
binding (folds former P0-03). ``AuthVerifier`` resolves to the SDK
:class:`kailash.delegate.verifier.Ed25519Verifier`; this module is its one
consumer, so the binding is used, never an imported-by-nobody orphan. There is no
local ``AuthVerifier`` placeholder.

Two distinct signing surfaces (both host-key-derived; the connector holds neither)
==================================================================================
- :class:`HostSigner` (P0-08b) signs **connector-receipt** bytes — the
  forge-closed surface that signs ONLY side effects the P0-08a seam observed.
  Exposed on the returned :class:`ComposedRuntime` as ``host_signer`` / ``seam``.
- The SDK ``DispatchSurface`` / ``DelegateRuntime`` ``signer`` slot signs the
  spine's own **audit-event** pre-image (``{event_type, event_payload,
  signer_delegate_id}`` — a DIFFERENT pre-image from the connector receipt, per
  ``dispatch_observation`` module docstring). It is a host-key-derived thunk; the
  connector never receives it.

What this shard does NOT do (later shards)
==========================================
- **Protocol-version negotiation** (reading the connector's declared
  ``delegate_host_protocol`` and refusing unsupported ranges with a loud
  load-time error, architecture §3.3) is **P0-10b**. Split out per the capacity
  HIGH finding — the ceremony wiring and the protocol gate's net-new control-flow
  overflowed the per-shard invariant ceiling together.
- **Wiring the reference connectors onto the host signer** (so the connector at
  ``connector.py:160``/``:184`` loses its raw key) is **P0-09 / P0-11**. Like the
  broker (P0-07), seam (P0-08a), and signer (P0-08b) this factory composes, the
  factory itself is a transitional surface until those shards land.

ZERO kailash spine edits: this module composes around the SDK dispatch types. See
``workspaces/connector-platform/02-plans/01-architecture.md`` §3.3 + §3.5 layer 2.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import (
    AuditChainEngine,
    DelegateIdentity,
    DelegateRuntime,
    DispatchSurface,
    PrincipalDirectory,
)
from kailash.delegate.dispatch import Connector, SignatureContract
from kailash.delegate.envelope import DelegateConstraintEnvelope
from kailash.delegate.trust import TenantScope, TenantScopedCascade
from kailash.delegate.types import (
    CapabilitySet,
    DelegateGenesisRecord,
    Role,
    RoleLifecycleState,
    RoleScope,
)
from kailash.trust._json import canonical_json_dumps
from kailash.trust.chain import AuthorityType, GenesisRecord, TrustLineageChain
from kailash.trust.envelope import ConstraintEnvelope

from delegate_connectors_host.dispatch_observation import DispatchObservationSeam
from delegate_connectors_host.dispatch_signing import HostSigner
from delegate_connectors_host.trust_primitives import AuthVerifier

__all__ = ["ComposedRuntime", "BuildConnector", "connector_builder"]


# The caller-supplied connector-build thunk. The factory builds the trust core
# first and hands the thunk the host-owned ``verifier`` + the cascade
# ``tenant_id``; the thunk closes over the connector's own transports/resolver
# and returns a constructed :class:`Connector`. It MUST construct the connector
# AROUND the supplied verifier (``connector.auth_verifier is verifier``) — the
# factory rejects a connector that built a parallel verifier.
BuildConnector = Callable[[AuthVerifier, str], Connector]


@dataclass(frozen=True, slots=True)
class ComposedRuntime:
    """The composed runtime plus every handle a caller needs to drive it.

    ``runtime.execute(payload)`` is the dispatch entry. ``host_signer`` + ``seam``
    are the forge-closed connector-receipt signing surface (P0-08a/P0-08b): the
    host observes a side effect through ``seam`` and signs the resulting ticket
    with ``host_signer`` — receipts so signed verify under ``verifier``.
    """

    runtime: DelegateRuntime
    dispatch_surface: DispatchSurface
    connector: Connector
    verifier: AuthVerifier
    identity: DelegateIdentity
    audit_engine: AuditChainEngine
    cascade: TenantScopedCascade
    seam: DispatchObservationSeam
    host_signer: HostSigner


def connector_builder(
    build_connector: BuildConnector,
    *,
    signature: SignatureContract,
    tenant_id: str = "tenant-connector-v0",
    signing_key: Ed25519PrivateKey | None = None,
) -> ComposedRuntime:
    """Compose a runnable ``DelegateRuntime`` around a host-built connector.

    The factory mints the trust core (host-owned key → directory → ``AuthVerifier``
    → seam → ``HostSigner``), builds the connector via ``build_connector`` around
    that verifier, derives the genesis/role capabilities from the connector's own
    ``requires_capabilities`` ABC declaration, and finishes the ceremony. The
    returned runtime is reusable and holds no per-call global state.

    Args:
        build_connector: ``(verifier, tenant_id) -> Connector`` thunk. Called once,
            after the trust core exists; MUST construct the connector around the
            supplied verifier (the factory asserts ``connector.auth_verifier is
            verifier``).
        signature: the application-supplied dispatch signature (a
            ``SignatureContract``: ``name`` + ``input_schema`` + ``output_schema``)
            handed to the ``DispatchSurface``.
        tenant_id: the tenant the cascade and connector operate under.
        signing_key: optional host Ed25519 key; minted if absent. The host holds
            it — the connector receives neither the key nor a signer thunk. Its
            public half is registered in the directory so host-signed receipts
            verify under the composed verifier.

    Returns:
        A :class:`ComposedRuntime` exposing the runtime, the host-observation seam,
        and the host signer.

    Raises:
        TypeError: ``build_connector`` did not return a :class:`Connector`.
        ValueError: the returned connector authenticates against a verifier other
            than the host-owned one (a parallel/forged verifier).
    """
    sk = signing_key or Ed25519PrivateKey.generate()
    pk_bytes = sk.public_key().public_bytes_raw()

    delegate_id = uuid.uuid4()
    identity = DelegateIdentity(
        delegate_id=delegate_id,
        sovereign_ref="connector-sovereign",
        role_binding_ref="connector-role-binding",
        genesis_ref="connector-genesis",
        principal_kind="delegate",
    )

    # The single canonical host binding: AuthVerifier IS the SDK Ed25519Verifier
    # (folds former P0-03). This module is its one consumer — used here, never an
    # imported-by-nobody orphan; there is no local AuthVerifier placeholder.
    directory = PrincipalDirectory(
        identities=(identity,),
        verification_keys={delegate_id: pk_bytes},
    )
    verifier = AuthVerifier(directory)

    # The host owns the key; the connector receives only the verifier. The seam
    # observes side effects and the signer signs ONLY what the seam observed —
    # the forge-closed connector-receipt signing surface (P0-08a/P0-08b).
    seam = DispatchObservationSeam()
    host_signer = HostSigner(seam, sk)

    # Build the connector AROUND the host-owned verifier (build-thunk shape). A
    # connector that constructs its own verifier is the forge oracle this shard
    # closes — reject it.
    connector = build_connector(verifier, tenant_id)
    if not isinstance(connector, Connector):
        raise TypeError(
            "build_connector MUST return a Connector; got "
            f"{type(connector).__name__}"
        )
    if connector.auth_verifier is not verifier:
        raise ValueError(
            "the connector MUST authenticate against the host-owned verifier "
            "(connector.auth_verifier is the factory's verifier) — a connector "
            "that built its own verifier is the forge oracle Phase 0 closes; "
            "construct the connector around the verifier the thunk was handed"
        )

    # Capabilities are the connector's OWN declared ABC contract — not a
    # hand-copied literal. Sorted for a deterministic genesis/role capability set.
    capabilities = tuple(sorted(connector.requires_capabilities))
    domain = connector.connector_kind

    genesis_block = GenesisRecord(
        id=f"{domain}-genesis-block",
        agent_id=str(delegate_id),
        authority_id=f"{domain}-connector-authority",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    chain = TrustLineageChain(genesis=genesis_block)
    audit_engine = AuditChainEngine(chain=chain, verifier=verifier)

    delegate_genesis = DelegateGenesisRecord(
        block=genesis_block, spec_version="0", capabilities=capabilities
    )
    envelope = DelegateConstraintEnvelope.from_genesis(
        ConstraintEnvelope(), delegate_genesis
    )

    # Tenant cascade; register the dispatch identity as root grantee with a real
    # Ed25519 grant proof (a wired verifier refuses an unsigned seed).
    tenant = TenantScope.for_tenant(tenant_id)
    cascade = TenantScopedCascade(tenant=tenant, verifier=verifier)
    grant_canonical = canonical_json_dumps(
        {"delegate_id": str(delegate_id), "tenant": tenant.tenant_id}
    ).encode("utf-8")
    cascade.register_root_grantee(identity, grant_proof=sk.sign(grant_canonical).hex())

    role = Role(
        role_id=uuid.uuid4(),
        display_name=f"{domain}-connector-role",
        scope=RoleScope(
            domain=domain,
            capabilities=CapabilitySet(capabilities=capabilities),
        ),
        lifecycle=RoleLifecycleState.ACTIVE,
    )

    # The SDK audit-event signing slot (spine's own audit pre-image, distinct from
    # the connector receipt). Host-key-derived; the connector never receives it.
    def audit_signer(canonical_bytes: bytes) -> str:
        return sk.sign(canonical_bytes).hex()

    dispatch_surface = DispatchSurface(
        connector,
        signature,
        envelope,
        identity,
        audit_engine=audit_engine,
        trust_cascade=cascade,
        role=role,
        signer=audit_signer,
        verifier=verifier,
    )
    runtime = DelegateRuntime(
        dispatch_surface=dispatch_surface,
        audit_engine=audit_engine,
        cascade=cascade,
        envelope=envelope,
        identity=identity,
        signer=audit_signer,
    )
    return ComposedRuntime(
        runtime=runtime,
        dispatch_surface=dispatch_surface,
        connector=connector,
        verifier=verifier,
        identity=identity,
        audit_engine=audit_engine,
        cascade=cascade,
        seam=seam,
        host_signer=host_signer,
    )
