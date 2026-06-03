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

Host-protocol negotiation gate (P0-10b)
=======================================
The factory reads the connector's declared ``delegate_host_protocol`` (an integer
``n`` meaning the single supported version ``{n}``, or an inclusive range
``[min, max]`` meaning ``{min..max}``; a connector that declares nothing defaults
to ``{1}``), intersects it with the host's supported set
:data:`HOST_SUPPORTED_PROTOCOLS` (``H``), and **loads iff** ``S ∩ H ≠ ∅`` —
binding the composition at ``max(S ∩ H)`` (surfaced as ``ComposedRuntime
.bound_protocol``). A disjoint declaration triggers a **loud load-time refusal**
(:class:`ProtocolUnsupportedError`) BEFORE the runtime is composed; the error
carries the portable, language-neutral attribute ``kind == 'protocol.unsupported'``
(protocol-spec §9) so the cross-impl conformance driver and a non-Python (Rust)
host assert on the ``kind`` string, NOT a Python class name. ``delegate_host_protocol``
is the **cross-impl wire-contract axis** — strictly independent of the SDK
``kailash>=2.28,<3`` dependency pin (protocol-spec §8); the two are never collapsed.

What this shard does NOT do (later shards)
==========================================
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

__all__ = [
    "ComposedRuntime",
    "BuildConnector",
    "connector_builder",
    "ProtocolUnsupportedError",
    "HOST_SUPPORTED_PROTOCOLS",
]


# ── Host-protocol negotiation (P0-10b) ────────────────────────────────────────

# The host's advertised supported set ``H`` for the cross-impl ``delegate_host_
# protocol`` wire contract. Today the only shipped wire contract is v1 (the
# canonical receipt protocol; ``specs/canonical-signing-bytes.md`` §1 pins
# ``protocol_version = 1``). When a v2 wire contract freezes, add ``2`` here — and
# ONLY here. This is the cross-impl wire-contract axis (protocol-spec §8); it is
# strictly independent of the SDK ``kailash>=2.28,<3`` Python-dependency pin. A
# Rust host has no ``kailash`` dependency but MUST advertise the same integer set.
HOST_SUPPORTED_PROTOCOLS: frozenset[int] = frozenset({1})

# The connector-declared default when a connector exposes no ``delegate_host_
# protocol``. v1 is the only shipped wire contract, so a connector that declares
# nothing speaks v1 — keeping the four v0 reference connectors (none of which
# declare a protocol yet; they are wired onto the host signer in P0-09/P0-11)
# loading at protocol 1 without modification.
_DEFAULT_PROTOCOL_DECLARATION = 1


class ProtocolUnsupportedError(ValueError):
    """Loud load-time refusal: connector ``S`` and host ``H`` share no protocol.

    Raised by :func:`connector_builder` BEFORE the runtime is composed when the
    connector's declared ``delegate_host_protocol`` set ``S`` is disjoint from
    :data:`HOST_SUPPORTED_PROTOCOLS` (``H``) — ``S ∩ H = ∅``.

    The forensic identity of this failure is the portable, language-neutral
    :attr:`kind` string ``'protocol.unsupported'`` (protocol-spec §9), NOT this
    Python class name. The cross-impl conformance driver and a non-Python (Rust)
    host both assert on ``err.kind``; the class name is a Python-side convenience
    only. Subclasses :class:`ValueError` so a generic load-error handler still
    catches it while the ``kind`` attribute names the specific refusal.
    """

    #: Portable, language-neutral failure identity (protocol-spec §9). The
    #: conformance driver asserts on THIS, never on the Python class name.
    kind: str = "protocol.unsupported"


def _declared_bounds(declared: object) -> tuple[int, int]:
    """Parse a ``delegate_host_protocol`` declaration into inclusive ``(lo, hi)``.

    Two declaration shapes per protocol-spec §8:

    - a bare ``int n`` → ``(n, n)`` (the connector supports exactly version ``n``);
    - an inclusive range as a 2-element ``[min, max]`` / ``(min, max)`` →
      ``(min, max)``.

    Returns the inclusive bounds WITHOUT materializing the set — the declared
    range may be arbitrarily wide and the intersection only ever needs the small
    host set ``H`` (see :func:`_negotiate_protocol`). Materializing
    ``range(lo, hi+1)`` for a well-formed but huge declaration (e.g.
    ``[1, 2**53-1]``) would OOM the host at load time — a connector-triggerable
    denial-of-service this representation structurally avoids.

    Any other shape (a malformed declaration — wrong type, wrong length, ``min >
    max``, non-int members, ``bool``) raises :class:`ValueError`. A malformed
    declaration is a connector bug distinct from a clean ``S ∩ H = ∅`` negotiation
    refusal, so it does NOT carry ``kind == 'protocol.unsupported'``.
    """
    # bool is an int subclass; reject it explicitly so True/False is not read as 1/0.
    if isinstance(declared, bool):
        raise ValueError(
            f"delegate_host_protocol must be an int or a 2-element [min, max] "
            f"range, not a bool; got {declared!r}"
        )
    if isinstance(declared, int):
        return (declared, declared)
    if isinstance(declared, (list, tuple)):
        if len(declared) != 2 or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in declared
        ):
            raise ValueError(
                f"delegate_host_protocol range must be a 2-element [min, max] of "
                f"ints; got {declared!r}"
            )
        lo, hi = declared
        if lo > hi:
            raise ValueError(
                f"delegate_host_protocol range min must be <= max; got [{lo}, {hi}]"
            )
        return (lo, hi)
    raise ValueError(
        f"delegate_host_protocol must be an int or a 2-element [min, max] range; "
        f"got {type(declared).__name__}"
    )


def _render_declared(declared: object, lo: int, hi: int) -> str:
    """Render the connector's DECLARED form for the refusal message (§8).

    An ``int n`` renders as ``n`` and a range renders as ``[lo, hi]`` — the
    literal declared shape, NOT the expanded set, so the message names "the
    connector's declared range" per §8 and matches a Rust impl's compact form.
    """
    return str(declared) if isinstance(declared, int) else f"[{lo}, {hi}]"


def _negotiate_protocol(connector: Connector) -> int:
    """Negotiate the bound protocol version, or refuse loudly at load time.

    Reads the connector-declared ``delegate_host_protocol`` (defaulting to ``1``
    — i.e. ``{1}`` — when the attribute is ABSENT; a connector that exposes the
    attribute but whose accessor raises is treated as non-declaring by the
    ``getattr`` default, the intended "absent → v1 backwards-compat" semantics),
    computes ``S ∩ H`` against :data:`HOST_SUPPORTED_PROTOCOLS` WITHOUT
    materializing ``S``, and returns ``max(S ∩ H)`` when the intersection is
    non-empty. A disjoint declaration raises :class:`ProtocolUnsupportedError`
    whose message names the connector kind, the connector's declared range, and
    the host's set.
    """
    declared = getattr(
        connector, "delegate_host_protocol", _DEFAULT_PROTOCOL_DECLARATION
    )
    lo, hi = _declared_bounds(declared)
    # Intersect against the SMALL host set H — never materialize the declared
    # range. O(|H|) regardless of how wide the connector's declaration is.
    common = frozenset(h for h in HOST_SUPPORTED_PROTOCOLS if lo <= h <= hi)
    if not common:
        raise ProtocolUnsupportedError(
            f"connector {connector.connector_kind!r} declares delegate_host_protocol "
            f"{_render_declared(declared, lo, hi)} but the host supports "
            f"{sorted(HOST_SUPPORTED_PROTOCOLS)} — no common protocol version "
            f"(S ∩ H = ∅); refusing to load. delegate_host_protocol is the "
            f"cross-impl wire-contract axis, independent of the kailash SDK "
            f"dependency pin (protocol-spec §8)."
        )
    return max(common)


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
    ``bound_protocol`` is the negotiated ``max(S ∩ H)`` host-protocol version the
    composition operates under (P0-10b).
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
    bound_protocol: int


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
    that verifier, negotiates the host protocol (``max(S ∩ H)``; loud load-time
    refusal on ``S ∩ H = ∅`` — P0-10b), derives the genesis/role capabilities from
    the connector's own ``requires_capabilities`` ABC declaration, and finishes the
    ceremony. The returned runtime is reusable and holds no per-call global state.

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
        the host signer, and the negotiated ``bound_protocol`` version.

    Raises:
        TypeError: ``build_connector`` did not return a :class:`Connector`.
        ValueError: the returned connector authenticates against a verifier other
            than the host-owned one (a parallel/forged verifier), OR the
            connector's ``delegate_host_protocol`` declaration is malformed.
        ProtocolUnsupportedError: the connector's declared ``delegate_host_protocol``
            set ``S`` is disjoint from :data:`HOST_SUPPORTED_PROTOCOLS` (``S ∩ H =
            ∅``). Carries the portable ``kind == 'protocol.unsupported'`` attribute.
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

    # Host-protocol negotiation (P0-10b): a LOUD load-time refusal on S ∩ H = ∅,
    # raised BEFORE any trust-core composition object (seam, signer, cascade,
    # dispatch surface, runtime) is built. Binds at max(S ∩ H).
    bound_protocol = _negotiate_protocol(connector)

    # The host owns the key; the connector receives only the verifier. The seam
    # observes side effects and the signer signs ONLY what the seam observed —
    # the forge-closed connector-receipt signing surface (P0-08a/P0-08b).
    seam = DispatchObservationSeam()
    host_signer = HostSigner(seam, sk)

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
        bound_protocol=bound_protocol,
    )
