# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Compose a runnable ``DelegateRuntime`` around a :class:`SlackConnector`.

Builds the full shipped composition — ``PrincipalDirectory`` +
``Ed25519Verifier``, in-memory ``AuditChainEngine`` over a ``TrustLineageChain``,
``TenantScopedCascade`` (root grantee registered with a real Ed25519 grant
proof), ``Role``, ``DispatchSurface``, and ``DelegateRuntime`` — using the
spine-shipped concretes for everything except the connector. No mocks; no
Postgres; no PACT (the shipped runtime audit is in-memory).

The runtime is constructed with a real ``Ed25519Verifier`` (NOT ``NullVerifier``)
and a real Ed25519 ``signer``. All constructors succeed and the composition
passes the runtime's R2-composition gate.

KNOWN SDK BLOCKER — ``runtime.execute()``:
    The shipped ``kailash.delegate`` runtime/dispatch audit-emit path signs the
    event PAYLOAD bytes (``DelegateRuntime._emit_phase_audit`` / the
    ``DispatchSurface.dispatch`` audit loop), but ``AuditChainEngine.emit_event``
    verifies the signature against the FULL audit-entry signing bytes
    (``AuditChainEntry.to_signing_bytes()`` — sequence + previous_hash +
    event_type + event_payload + signer + signed_at). The two byte strings are
    never equal, so ``emit_event`` raises ``AuditChainSignatureError`` on the
    first phase transition and ``runtime.execute()`` returns
    ``taod_state.phase == "failed"`` under ANY real verifier. This is a bug in
    the SDK runtime, NOT in this connector — the connector's own ``read`` /
    ``write`` receipts verify correctly (proven in the Tier-1 suite). See
    ``workspaces/email/journal/0005-GAP-*`` for the full reproduction (same SDK
    failure mode reproduces for slack — both connectors hit the same gate).
    Tracked as kailash-py#1182. The end-to-end ``execute()`` assertion is gated
    on the SDK fix; composition (everything this module does up to
    ``build_slack_runtime``) is not.
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

from delegate_connectors.slack.connector import SlackConnector
from delegate_connectors.slack.directory import SlackPrincipalResolver
from delegate_connectors.slack.web_api import SlackTransport

__all__ = [
    "SlackV0Signature",
    "ComposedSlackRuntime",
    "build_slack_runtime",
]


@dataclass(frozen=True, slots=True)
class SlackV0Signature:
    """Minimal application-supplied dispatch signature (v0 fixture).

    Satisfies the shipped ``SignatureContract`` Protocol (``name`` +
    ``input_schema`` + ``output_schema``). This is a DOCUMENTED v0 placeholder:
    real applications supply their own structured signature. It is NOT a
    stub-for-production — it is the genuine, minimal v0 dispatch contract for a
    Slack post, and it is honored by the dispatch surface's input validation.
    """

    name: str = "slack-post"
    input_schema: dict[str, type] | None = None
    output_schema: dict[str, type] | None = None

    def __post_init__(self) -> None:
        if self.input_schema is None:
            object.__setattr__(
                self,
                "input_schema",
                {"channel": str, "text": str},
            )
        if self.output_schema is None:
            object.__setattr__(
                self,
                "output_schema",
                {"ok": bool, "ts": str, "channel": str},
            )


@dataclass(frozen=True, slots=True)
class ComposedSlackRuntime:
    """The composed runtime plus the handles a caller needs to drive it.

    ``runtime.execute(payload)`` is the dispatch entry (see the module-level
    KNOWN SDK BLOCKER). ``connector`` is the bound :class:`SlackConnector`;
    ``verifier`` verifies every receipt the connector signs; ``identity`` is the
    dispatch identity registered as the cascade root grantee.
    """

    runtime: DelegateRuntime
    dispatch_surface: DispatchSurface
    connector: SlackConnector
    verifier: Ed25519Verifier
    identity: DelegateIdentity
    audit_engine: AuditChainEngine


def build_slack_runtime(
    *,
    transport: SlackTransport,
    sender_slack_id: str,
    sender_principal_tenant: str = "tenant-slack-v0",
    signing_key: Ed25519PrivateKey | None = None,
) -> ComposedSlackRuntime:
    """Compose a real ``DelegateRuntime`` around a :class:`SlackConnector`.

    All trust/audit/verifier concretes are the spine-shipped ones; only the
    connector is connector-specific. The returned runtime is reusable and holds
    no per-call global state.

    Args:
        transport: the connector's Slack Web API transport (point it at the
            Tier-2 mock-server container in integration tests via
            ``SLACK_API_BASE_URL``, the live Slack API in production).
        sender_slack_id: the Slack id the dispatch identity authenticates as
            (the primary resolver key is ``delegate_id`` per ADR-S2; this Slack
            id is the SECONDARY index for payload attribution).
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
        sovereign_ref="slack-connector-sovereign",
        role_binding_ref="slack-connector-role-binding",
        genesis_ref="slack-connector-genesis",
        principal_kind="delegate",
    )

    directory = PrincipalDirectory(
        identities=(identity,),
        verification_keys={delegate_id: pk_bytes},
    )
    verifier = Ed25519Verifier(directory)

    # In-memory audit chain (no Postgres) gated by the same verifier class.
    genesis_block = GenesisRecord(
        id="slack-genesis-block",
        agent_id=str(delegate_id),
        authority_id="slack-connector-authority",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    chain = TrustLineageChain(genesis=genesis_block)
    audit_engine = AuditChainEngine(chain=chain, verifier=verifier)

    delegate_genesis = DelegateGenesisRecord(
        block=genesis_block, spec_version="0", capabilities=("slack.post",)
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
        display_name="slack-connector-role",
        scope=RoleScope(
            domain="slack",
            capabilities=CapabilitySet(capabilities=("slack.post",)),
        ),
        lifecycle=RoleLifecycleState.ACTIVE,
    )

    resolver = SlackPrincipalResolver(
        {
            sender_slack_id: Principal(
                delegate_id=str(delegate_id),
                tenant_id=tenant.tenant_id,
                claims={"slack_user_id": sender_slack_id},
            )
        }
    )

    connector = SlackConnector(
        transport=transport,
        resolver=resolver,
        signing_key=sk,
        verifier=verifier,
        tenant_id=tenant.tenant_id,
    )

    dispatch_surface = DispatchSurface(
        connector,
        SlackV0Signature(),
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
    return ComposedSlackRuntime(
        runtime=runtime,
        dispatch_surface=dispatch_surface,
        connector=connector,
        verifier=verifier,
        identity=identity,
        audit_engine=audit_engine,
    )
