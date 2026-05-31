# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Per-vector conformance driver for the canonical delegate vector set.

Each canonical vector (DV-3/5/7/9/10) asserts a RUNTIME-level invariant of
``kailash.delegate`` — envelope monotonic-tightening, cascade-grant validation,
TAOD single-shot phase monotonicity, audit-chain round-trip stability, and the
sovereign-vs-service-account principal separation. The connector is the dispatch
target; the vectors themselves are connector-AGNOSTIC (they exercise the shipped
delegate spine, not connector-specific code).

``drive_vector(vector, make_composed)`` materializes the vector's ``given`` using
the shipped ``kailash.delegate`` primitives and returns the observed
``BehaviouralOutcome``:

* ``Accept`` — the composition / round-trip / execute path succeeds.
* ``Reject`` — the path raises one of the spine's monotonic-tightening /
  cascade-scope / phase-monotonicity / principal-separation violation errors,
  OR ``runtime.execute()`` returns ``phase == "failed"``.

This module is copied per-connector (mirroring how ``loader.py`` is mirrored) so
each connector's conformance suite stays self-contained — there is NO
cross-connector import. Only the ``make_composed`` thunk passed in by the
connector's test module differs; the vector logic below is identical everywhere.

No mocks: every primitive is the real shipped concrete. The only test double is
the connector's transport (a protocol-faithful double over a real socket, or the
composition-only no-op client the connector test supplies) — exactly as the
Tier-2 e2e suite does.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import (
    AuditChainEngine,
    AuditChainEntry,
    CascadeScopeExpansionError,
    CascadeTenantViolationError,
    CapabilitySet,
    DelegateConstraintEnvelope,
    DelegateGenesisRecord,
    DelegateIdentity,
    DispatchCascadeViolationError,
    DispatchEnvelopeViolationError,
    DispatchSurface,
    Ed25519Verifier,
    EnvelopeWideningError,
    PrincipalDirectory,
    R2CompositionError,
    Role,
    RoleLifecycleState,
    RoleScope,
    RuntimeCompositionError,
    RuntimePhaseError,
    RuntimePostureBlockedError,
    TenantScope,
    TenantScopedCascade,
)
from kailash.delegate.conformance.schema import BehaviouralOutcome, ConformanceVector
from kailash.trust._json import canonical_json_dumps
from kailash.trust.chain import AuthorityType, GenesisRecord
from kailash.trust.envelope import ConstraintEnvelope, FinancialConstraint

# The closed family of spine-level violation errors that map a raised path to
# the ``Reject`` outcome. Each corresponds to a documented delegate-spec
# invariant; a raise from any of them is the runtime refusing the triplet.
_REJECT_ERRORS: tuple[type[Exception], ...] = (
    EnvelopeWideningError,
    CascadeScopeExpansionError,
    CascadeTenantViolationError,
    DispatchCascadeViolationError,
    DispatchEnvelopeViolationError,
    R2CompositionError,
    RuntimePhaseError,
    RuntimeCompositionError,
    RuntimePostureBlockedError,
)


def _fresh_genesis() -> tuple[GenesisRecord, DelegateGenesisRecord]:
    """A minimal Genesis Record + DelegateGenesisRecord pair (Spec §3 anchor)."""
    block = GenesisRecord(
        id="conformance-genesis",
        agent_id=str(uuid.uuid4()),
        authority_id="conformance-authority",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    dgen = DelegateGenesisRecord(
        block=block, spec_version="0", capabilities=("conformance.act",)
    )
    return block, dgen


def _bounded_envelope(max_spend_usd: float) -> DelegateConstraintEnvelope:
    """A delegate envelope whose Financial dimension is bounded at ``max_spend_usd``."""
    _, dgen = _fresh_genesis()
    return DelegateConstraintEnvelope.from_genesis(
        ConstraintEnvelope(financial=FinancialConstraint(max_spend_usd=max_spend_usd)),
        dgen,
    )


# ── DV-3 §3 — Genesis + cascade grant widening Financial in one lifecycle ──


def _drive_dv3() -> BehaviouralOutcome:
    """A TenantScopedCascade grant whose child envelope WIDENS the parent's
    Financial dimension within one lifecycle. R2 composition (the cascade edge)
    MUST reject the triplet — widening violates monotonic tightening in a single
    lifecycle (Spec §3). The reject signal is ``EnvelopeWideningError`` raised by
    ``cascade_child`` Step 3 (F5 envelope tightening).
    """
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key().public_bytes_raw()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    parent_identity = DelegateIdentity(
        delegate_id=parent_id,
        sovereign_ref="dv3-sovereign",
        role_binding_ref="dv3-parent-rb",
        genesis_ref="dv3-genesis",
        principal_kind="delegate",
    )
    child_identity = DelegateIdentity(
        delegate_id=child_id,
        sovereign_ref="dv3-sovereign",
        role_binding_ref="dv3-child-rb",
        genesis_ref="dv3-genesis",
        principal_kind="delegate",
    )
    directory = PrincipalDirectory(
        identities=(parent_identity, child_identity),
        verification_keys={parent_id: pk, child_id: pk},
    )
    verifier = Ed25519Verifier(directory)
    tenant = TenantScope.for_tenant("tenant-dv3")
    cascade = TenantScopedCascade(tenant=tenant, verifier=verifier)

    parent_env = _bounded_envelope(100.0)
    # Child grant attempts to WIDEN Financial (1000 > 100) — the §3 violation.
    child_env = _bounded_envelope(1000.0)
    scope = RoleScope(
        domain="conformance",
        capabilities=CapabilitySet(capabilities=("conformance.act",)),
    )
    granted_at = datetime.now(timezone.utc)
    grant_canonical = canonical_json_dumps(
        {
            "parent_delegate_id": str(parent_id),
            "child_delegate_id": str(child_id),
            "tenant": tenant.tenant_id,
            "granted_at": granted_at.isoformat(),
        }
    ).encode("utf-8")
    grant_proof = sk.sign(grant_canonical).hex()
    try:
        cascade.cascade_child(
            parent_env,
            child_env,
            parent_identity=parent_identity,
            child_identity=child_identity,
            parent_scope=scope,
            child_scope=scope,
            child_tenant=tenant,
            grant_proof=grant_proof,
            granted_at=granted_at,
        )
    except _REJECT_ERRORS:
        return BehaviouralOutcome.REJECT
    return BehaviouralOutcome.ACCEPT


# ── DV-5 §5 — Delegation envelope widening Financial relative to G ─────────


def _drive_dv5() -> BehaviouralOutcome:
    """A Delegation's constraint envelope WIDENS the Financial dimension relative
    to its Genesis envelope. A delegated envelope may only tighten (Spec §5);
    widening within a single lifecycle MUST be rejected (``EnvelopeWideningError``
    from ``tighten_with``). Widening requires a new Genesis Record.
    """
    genesis_envelope = _bounded_envelope(100.0)
    wider = ConstraintEnvelope(financial=FinancialConstraint(max_spend_usd=1000.0))
    try:
        genesis_envelope.tighten_with(wider)
    except _REJECT_ERRORS:
        return BehaviouralOutcome.REJECT
    return BehaviouralOutcome.ACCEPT


# ── DV-7 §7 — second execute() on a terminal runtime ───────────────────────


async def _drive_dv7(make_composed: Callable[[], object]) -> BehaviouralOutcome:
    """Drive a runtime through the TAOD lifecycle to a terminal phase, then invoke
    ``execute()`` a SECOND time on the same terminal runtime. TAOD transitions are
    append-only — once terminal, no further phase transitions are accepted
    (Spec §7, ``RuntimePhaseError``). The second invocation MUST be rejected.

    The first run reaches a terminal TAOD state (the spine marks the runtime
    single-shot regardless of the first run's Accept/Reject outcome); the SECOND
    ``execute()`` is the asserted §7 reject.
    """
    composed = make_composed()
    await composed.runtime.execute(_conformance_payload(composed))
    try:
        await composed.runtime.execute(_conformance_payload(composed))
    except _REJECT_ERRORS:
        return BehaviouralOutcome.REJECT
    return BehaviouralOutcome.ACCEPT


# ── DV-9 §9 — AuditChain head-hash round-trip re-validation ────────────────


async def _drive_dv9(make_composed: Callable[[], object]) -> BehaviouralOutcome:
    """A successful execution produces an ``AuditChainEngine`` head hash; a replay
    built from the persisted audit entries via canonical-dict round-trip MUST
    re-validate the SAME head hash. Audit-chain entries are deterministic and the
    head hash is byte-shape-stable across ``to_canonical_dict()`` round-trips
    (Spec §9). Re-validation succeeding is the ``Accept`` signal.
    """
    composed = make_composed()
    await composed.runtime.execute(_conformance_payload(composed))
    engine: AuditChainEngine = composed.audit_engine

    original_head = engine.head_hash()
    if original_head is None:
        # An empty chain cannot demonstrate the §9 round-trip property.
        return BehaviouralOutcome.REJECT

    # Persist every entry via its canonical dict, then reconstruct each
    # AuditChainEntry from the persisted form (the replay) and recompute the
    # head hash. A byte-shape-stable round-trip reproduces the head hash exactly.
    persisted = [entry.to_canonical_dict() for entry in engine.entries]
    replayed = [_entry_from_canonical_dict(d) for d in persisted]
    replay_head_canonical = canonical_json_dumps(replayed[-1].to_canonical_dict())
    replay_head = hashlib.sha256(replay_head_canonical.encode("utf-8")).hexdigest()

    return (
        BehaviouralOutcome.ACCEPT
        if replay_head == original_head
        else BehaviouralOutcome.REJECT
    )


def _entry_from_canonical_dict(payload: dict) -> AuditChainEntry:
    """Reconstruct an ``AuditChainEntry`` from its ``to_canonical_dict()`` form.

    The canonical dict serializes ``sequence`` as a string, ``signer_delegate_id``
    as a UUID string, and ``signed_at`` as an ISO-8601 string; the constructor
    takes the native types. The reconstruction is exact — re-serializing the
    rebuilt entry's canonical dict reproduces byte-identical content (verified by
    the head-hash equality in :func:`_drive_dv9`).
    """
    return AuditChainEntry(
        sequence=int(payload["sequence"]),
        previous_hash=payload["previous_hash"],
        event_type=payload["event_type"],
        event_payload=payload["event_payload"],
        signer_delegate_id=uuid.UUID(str(payload["signer_delegate_id"])),
        signed_at=datetime.fromisoformat(payload["signed_at"]),
        signature=payload["signature"],
    )


# ── DV-10 §10 — Connector service-account principal identical to sovereign ─


def _drive_dv10(make_composed: Callable[[], object]) -> BehaviouralOutcome:
    """A Connector binds a principal IDENTICAL to the sovereign principal the
    Delegate acts for. A Delegate MUST act through a scoped service-account
    principal DISTINCT from the sovereign principal — an identical principal is
    impersonation that collapses the Genesis-to-Delegation attribution chain
    (Spec §10). The bind MUST be rejected (``DispatchEnvelopeViolationError`` from
    the §10 G1 principal-kind discriminator gate).

    Materialization: bind a ``principal_kind="sovereign"`` identity (the service
    account claiming to BE the sovereign principal) to the connector's role whose
    ``permitted_principal_kinds`` is the scoped service-account set only. The
    sovereign principal is not permitted on the connector's service-account role;
    the bind raises. The connector under test is reused from the composed bundle;
    everything else is a fresh, fully-wired (registered grantee, matching
    verifier) trust scaffold so the principal-kind mismatch is the sole violation.
    """
    composed = make_composed()
    connector = composed.connector

    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key().public_bytes_raw()

    def signer(canonical_bytes: bytes) -> str:
        return sk.sign(canonical_bytes).hex()

    delegate_id = uuid.uuid4()
    # The impersonating identity: a service account whose principal IS the
    # sovereign principal (principal_kind="sovereign").
    sovereign_identity = DelegateIdentity(
        delegate_id=delegate_id,
        sovereign_ref="dv10-sovereign",
        role_binding_ref="dv10-rb",
        genesis_ref="dv10-genesis",
        principal_kind="sovereign",
    )
    directory = PrincipalDirectory(
        identities=(sovereign_identity,),
        verification_keys={delegate_id: pk},
    )
    verifier = Ed25519Verifier(directory)
    tenant = TenantScope.for_tenant("tenant-dv10")
    cascade = TenantScopedCascade(tenant=tenant, verifier=verifier)
    grant_canonical = canonical_json_dumps(
        {"delegate_id": str(delegate_id), "tenant": tenant.tenant_id}
    ).encode("utf-8")
    cascade.register_root_grantee(
        sovereign_identity, grant_proof=sk.sign(grant_canonical).hex()
    )

    block, dgen = _fresh_genesis()
    chain = _trust_chain(block)
    audit_engine = AuditChainEngine(chain=chain, verifier=verifier)
    envelope = DelegateConstraintEnvelope.from_genesis(ConstraintEnvelope(), dgen)

    # The connector's role admits ONLY a scoped service-account principal —
    # distinct from the sovereign. A sovereign principal binding here is the
    # §10 impersonation the gate refuses.
    service_account_role = Role(
        role_id=uuid.uuid4(),
        display_name="connector-service-account-role",
        scope=RoleScope(
            domain="conformance",
            capabilities=CapabilitySet(capabilities=("conformance.act",)),
        ),
        lifecycle=RoleLifecycleState.ACTIVE,
        permitted_principal_kinds=frozenset({"service_account"}),
    )

    try:
        DispatchSurface(
            connector,
            composed.dispatch_surface.signature,
            envelope,
            sovereign_identity,
            audit_engine=audit_engine,
            trust_cascade=cascade,
            role=service_account_role,
            signer=signer,
            verifier=verifier,
        )
    except _REJECT_ERRORS:
        return BehaviouralOutcome.REJECT
    return BehaviouralOutcome.ACCEPT


def _trust_chain(block: GenesisRecord):
    """Build an in-memory ``TrustLineageChain`` rooted at ``block``."""
    from kailash.trust.chain import TrustLineageChain

    return TrustLineageChain(genesis=block)


def _conformance_payload(composed: object) -> dict:
    """The minimal dispatch payload the composed connector accepts.

    Read from the composed dispatch surface's signature input schema so the
    payload shape is correct for whichever connector supplied ``make_composed``.
    A composition's ``SignatureContract.input_schema`` declares the field names
    + types; we fill each declared ``str`` field with a deterministic stub value.
    """
    schema = composed.dispatch_surface.signature.input_schema or {}
    payload: dict = {}
    for field_name, field_type in schema.items():
        if field_type is str:
            payload[field_name] = f"conformance-{field_name}"
        elif field_type is int:
            payload[field_name] = 0
        elif field_type is bool:
            payload[field_name] = False
        else:
            payload[field_name] = f"conformance-{field_name}"
    return payload


async def drive_two_deterministic_runs(
    make_composed: Callable[[], object],
) -> tuple[dict, dict]:
    """Execute two INDEPENDENT composed runtimes on identical input and return
    their ``RuntimeExecutionResult.to_dict()`` receipt trees.

    Identical inputs MUST yield agreeing receipts once the per-run-by-design
    fields are excluded (``run_id``, the per-transition ``at`` timestamp,
    ``dispatch_id``, ``audit_head_hash``, ``audit_chain_entries``). This is the
    cross-run determinism property the canonical set asks v0 to demonstrate
    (Spec §9 receipt agreement); the caller asserts it via
    ``assert_receipts_agree`` with the same ``exclude_fields`` as the Tier-2 e2e
    determinism test.
    """
    composed_a = make_composed()
    composed_b = make_composed()
    payload = _conformance_payload(composed_a)
    result_a = await composed_a.runtime.execute(dict(payload))
    result_b = await composed_b.runtime.execute(dict(payload))
    return result_a.to_dict(), result_b.to_dict()


async def drive_vector(
    vector: ConformanceVector,
    make_composed: Callable[[], object],
) -> BehaviouralOutcome:
    """Materialize ``vector.given`` against the shipped delegate spine and return
    the observed ``BehaviouralOutcome``.

    ``make_composed`` is a zero-arg thunk returning a fresh composed runtime
    bundle for the connector under test (the connector's
    ``Composed*Runtime``). DV-7 needs a fresh runtime per invocation (the spine
    is single-shot); DV-9 needs a freshly-run audit engine; DV-10 needs the
    connector handle. DV-3 / DV-5 are connector-agnostic and need no composition.

    Raises ``KeyError`` (via the dispatch table) for an unknown vector id — a
    NEW canonical vector MUST add a driver branch here rather than silently
    defaulting, so an un-materialized vector fails loudly instead of faking.
    """
    vector_id = vector.id
    if vector_id == "DV-3-001":
        return _drive_dv3()
    if vector_id == "DV-5-001":
        return _drive_dv5()
    if vector_id == "DV-7-001":
        return await _drive_dv7(make_composed)
    if vector_id == "DV-9-001":
        return await _drive_dv9(make_composed)
    if vector_id == "DV-10-001":
        return _drive_dv10(make_composed)
    raise KeyError(
        f"no conformance driver for vector {vector_id!r}; a new canonical vector "
        "MUST add a driver branch in vector_driver.drive_vector (do not default — "
        "an un-materialized vector must fail loudly, never fake an outcome)"
    )
