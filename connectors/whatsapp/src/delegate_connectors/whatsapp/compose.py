# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Compose a runnable ``DelegateRuntime`` around a :class:`WhatsAppConnector`.

Builds the full shipped composition — ``PrincipalDirectory`` +
``Ed25519Verifier``, in-memory ``AuditChainEngine`` over a
``TrustLineageChain``, ``TenantScopedCascade`` (root grantee registered with a
real Ed25519 grant proof), ``Role``, ``DispatchSurface``, and
``DelegateRuntime`` — using the spine-shipped concretes for everything except
the connector. No mocks; no Postgres; no PACT (the shipped runtime audit is
in-memory).

The runtime is constructed with a real ``Ed25519Verifier`` (NOT
``NullVerifier``) and a real Ed25519 ``signer``. All constructors succeed and
the composition passes the runtime's R2-composition gate.

``runtime.execute()`` — end-to-end (fixed at kailash >= 2.28.0):
    Previously gated on kailash-py#1182 — the runtime/dispatch audit-emit path
    signed the event PAYLOAD bytes while ``AuditChainEngine.emit_event`` verified
    the FULL audit-entry signing bytes, so ``execute()`` returned
    ``taod_state.phase == "failed"`` under any real verifier at the first phase
    transition. Fixed at kailash <= 2.28.1 (the connector floor is now
    ``>=2.28.0``); ``runtime.execute()`` now completes end-to-end. See
    ``workspaces/whatsapp/journal/0008`` for the fix verification.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kailash.delegate import (
    AuditChainEngine,
    DelegateIdentity,
    DelegateRuntime,
    DispatchSurface,
    Ed25519Verifier,
    PrincipalDirectory,
)
from kailash.delegate.dispatch import Principal
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

from delegate_connectors.whatsapp.cloud_api import WhatsAppCloudApi
from delegate_connectors.whatsapp.connector import WhatsAppConnector
from delegate_connectors.whatsapp.directory import WhatsAppPrincipalResolver
from delegate_connectors.whatsapp.redaction import normalize_e164
from delegate_connectors.whatsapp.templates import (
    ServiceWindowTracker,
    TemplateGate,
)
from delegate_connectors.whatsapp.webhook import WebhookIngest

__all__ = [
    "WhatsAppV0Signature",
    "ComposedWhatsAppRuntime",
    "build_whatsapp_runtime",
]


@dataclass(frozen=True, slots=True)
class WhatsAppV0Signature:
    """Minimal application-supplied dispatch signature (v0 fixture).

    Satisfies the shipped ``SignatureContract`` Protocol (``name`` +
    ``input_schema`` + ``output_schema``). This is a DOCUMENTED v0
    placeholder: real applications supply their own structured signature. It
    is NOT a stub-for-production — it is the genuine, minimal v0 dispatch
    contract for a WhatsApp Cloud API ``/messages`` send, and it is honored
    by the dispatch surface's input validation.

    ``input_schema`` declares ``to`` (the bare-digit E.164 recipient) + a
    free-form ``text`` body. Template sends use the same surface with
    ``text=""`` + ``template_name`` set; the dispatch surface's basic
    isinstance check accepts the union shape via the most-common-first
    declaration.
    """

    name: str = "whatsapp-send"
    input_schema: dict[str, type] | None = None
    output_schema: dict[str, type] | None = None

    def __post_init__(self) -> None:
        if self.input_schema is None:
            object.__setattr__(
                self,
                "input_schema",
                {"to": str, "text": str},
            )
        if self.output_schema is None:
            object.__setattr__(
                self,
                "output_schema",
                {"wamid": str, "wa_id": str, "to": str},
            )


@dataclass(frozen=True, slots=True)
class ComposedWhatsAppRuntime:
    """The composed runtime plus the handles a caller needs to drive it.

    ``runtime.execute(payload)`` is the dispatch entry (see the module-level
    KNOWN SDK BLOCKER). ``connector`` is the bound
    :class:`WhatsAppConnector`; ``verifier`` verifies every receipt the
    connector signs; ``identity`` is the dispatch identity registered as the
    cascade root grantee.
    """

    runtime: DelegateRuntime
    dispatch_surface: DispatchSurface
    connector: WhatsAppConnector
    verifier: Ed25519Verifier
    identity: DelegateIdentity
    audit_engine: AuditChainEngine


def build_whatsapp_runtime(
    *,
    cloud_api: WhatsAppCloudApi,
    ingest: WebhookIngest,
    sender_phone: str,
    approved_templates: "set[str] | list[str] | tuple[str, ...]" = (),
    sender_principal_tenant: str = "tenant-whatsapp-v0",
    signing_key: Ed25519PrivateKey | None = None,
) -> ComposedWhatsAppRuntime:
    """Compose a real ``DelegateRuntime`` around a :class:`WhatsAppConnector`.

    All trust/audit/verifier concretes are the spine-shipped ones; only the
    connector is connector-specific. The returned runtime is reusable and
    holds no per-call global state.

    Args:
        cloud_api: the connector's Cloud API transport (point it at a local
            Cloud API double in integration tests, the real Meta Cloud API in
            production).
        ingest: the connector's webhook ingest buffer (shared with the
            verified-inbound path that feeds the template gate's window
            tracker).
        sender_phone: the E.164 phone number the dispatch identity
            authenticates as (the resolver's primary phone key). Normalized
            via :func:`normalize_e164` so callers can pass either ``+1...``
            or bare-digit form.
        approved_templates: the connector's approved-template allowlist —
            template names not in this set are pre-flight ``Reject``ed.
            Free-form sends to a recipient outside the open 24h
            customer-service window are also pre-flight ``Reject``ed.
        sender_principal_tenant: the tenant the connector operates under.
        signing_key: optional Ed25519 key; generated if absent. The matching
            public key is registered in the directory so the connector's
            receipts verify under the composed verifier.
    """
    sk = signing_key or Ed25519PrivateKey.generate()
    pk_bytes = sk.public_key().public_bytes_raw()

    def signer(canonical_bytes: bytes) -> str:
        # Ed25519 signature (64 bytes) -> 128-char lowercase hex, the
        # audit-engine + dispatch-surface signer contract.
        return sk.sign(canonical_bytes).hex()

    delegate_id = uuid.uuid4()
    identity = DelegateIdentity(
        delegate_id=delegate_id,
        sovereign_ref="whatsapp-connector-sovereign",
        role_binding_ref="whatsapp-connector-role-binding",
        genesis_ref="whatsapp-connector-genesis",
        principal_kind="delegate",
    )

    directory = PrincipalDirectory(
        identities=(identity,),
        verification_keys={delegate_id: pk_bytes},
    )
    verifier = Ed25519Verifier(directory)

    # In-memory audit chain (no Postgres) gated by the same verifier class.
    genesis_block = GenesisRecord(
        id="whatsapp-genesis-block",
        agent_id=str(delegate_id),
        authority_id="whatsapp-connector-authority",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    chain = TrustLineageChain(genesis=genesis_block)
    audit_engine = AuditChainEngine(chain=chain, verifier=verifier)

    delegate_genesis = DelegateGenesisRecord(
        block=genesis_block, spec_version="0", capabilities=("whatsapp.send",)
    )
    envelope = DelegateConstraintEnvelope.from_genesis(
        ConstraintEnvelope(), delegate_genesis
    )

    # Tenant cascade; register the dispatch identity as root grantee with a
    # real Ed25519 grant proof (a wired verifier refuses an unsigned seed).
    tenant = TenantScope.for_tenant(sender_principal_tenant)
    cascade = TenantScopedCascade(tenant=tenant, verifier=verifier)
    grant_canonical = canonical_json_dumps(
        {"delegate_id": str(delegate_id), "tenant": tenant.tenant_id}
    ).encode("utf-8")
    cascade.register_root_grantee(identity, grant_proof=sk.sign(grant_canonical).hex())

    role = Role(
        role_id=uuid.uuid4(),
        display_name="whatsapp-connector-role",
        scope=RoleScope(
            domain="whatsapp",
            capabilities=CapabilitySet(capabilities=("whatsapp.send",)),
        ),
        lifecycle=RoleLifecycleState.ACTIVE,
    )

    # Normalize the sender phone once and key the resolver by the bare-digit
    # form (the same shape the redactor sees on inbound). The Principal's
    # `claims` carry the BARE-DIGIT form too — the raw +E.164 lives only on
    # the inbound HTTPS body, not on any persisted record.
    sender_normalized = normalize_e164(sender_phone)
    principal = Principal(
        delegate_id=str(delegate_id),
        tenant_id=tenant.tenant_id,
        claims={"phone": sender_normalized},
    )
    resolver = WhatsAppPrincipalResolver({sender_normalized: principal})

    # Template / service-window pre-flight Reject gate. The window tracker
    # is bound to the ingest's verified-inbound sink so the gate's window
    # state is fed by the verified-webhook path (todo 06 + the L1 LRU bound
    # from todo 14 already on main).
    window_tracker = ServiceWindowTracker()
    # Re-bind the ingest's window sink in-place so verified inbounds open
    # the gate's window. The ingest was constructed without one; we mutate
    # the private field to wire the tracker — symmetric with how telegram
    # composes its resolver-against-transport.
    object.__setattr__(ingest, "_window_sink", window_tracker.record_inbound)
    template_gate = TemplateGate(approved_templates, window_tracker)

    connector = WhatsAppConnector(
        cloud_api=cloud_api,
        ingest=ingest,
        resolver=resolver,
        template_gate=template_gate,
        signing_key=sk,
        verifier=verifier,
        tenant_id=tenant.tenant_id,
    )

    dispatch_surface = DispatchSurface(
        connector,
        WhatsAppV0Signature(),
        envelope,
        identity,
        audit_engine=audit_engine,
        trust_cascade=cascade,
        role=role,
        signer=signer,
        verifier=verifier,
    )
    runtime = DelegateRuntime(
        dispatch_surface=dispatch_surface,
        audit_engine=audit_engine,
        cascade=cascade,
        envelope=envelope,
        identity=identity,
        signer=signer,
    )
    return ComposedWhatsAppRuntime(
        runtime=runtime,
        dispatch_surface=dispatch_surface,
        connector=connector,
        verifier=verifier,
        identity=identity,
        audit_engine=audit_engine,
    )
