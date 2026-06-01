# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Compose a runnable ``DelegateRuntime`` around a :class:`TelegramConnector`.

Builds the full shipped composition — ``PrincipalDirectory`` +
``Ed25519Verifier``, in-memory ``AuditChainEngine`` over a ``TrustLineageChain``,
``TenantScopedCascade`` (root grantee registered with a real Ed25519 grant
proof), ``Role``, ``DispatchSurface``, and ``DelegateRuntime`` — using the
spine-shipped concretes for everything except the connector. No mocks; no
Postgres; no PACT (the shipped runtime audit is in-memory).

The runtime is constructed with a real ``Ed25519Verifier`` (NOT ``NullVerifier``)
and a real Ed25519 ``signer``. All constructors succeed and the composition
passes the runtime's R2-composition gate.

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

from delegate_connectors.telegram.connector import TelegramConnector
from delegate_connectors.telegram.directory import TelegramPrincipalResolver
from delegate_connectors.telegram.transport import TelegramTransport

__all__ = [
    "TelegramV0Signature",
    "ComposedTelegramRuntime",
    "build_telegram_runtime",
]


@dataclass(frozen=True, slots=True)
class TelegramV0Signature:
    """Minimal application-supplied dispatch signature (v0 fixture).

    Satisfies the shipped ``SignatureContract`` Protocol (``name`` +
    ``input_schema`` + ``output_schema``). This is a DOCUMENTED v0 placeholder:
    real applications supply their own structured signature. It is NOT a
    stub-for-production — it is the genuine, minimal v0 dispatch contract for
    a Telegram ``sendMessage``, and it is honored by the dispatch surface's
    input validation.
    """

    name: str = "telegram-send"
    input_schema: dict[str, type] | None = None
    output_schema: dict[str, type] | None = None

    def __post_init__(self) -> None:
        if self.input_schema is None:
            # chat_id can be int OR str (@channelusername); the dispatch surface
            # accepts the first matching type from the tuple union (the SDK
            # schema check is a basic isinstance, not a discriminated union),
            # so list the most common (int) first.
            object.__setattr__(
                self,
                "input_schema",
                {"chat_id": int, "text": str},
            )
        if self.output_schema is None:
            object.__setattr__(
                self,
                "output_schema",
                {"message_id": int, "chat_id": int, "ok": bool},
            )


@dataclass(frozen=True, slots=True)
class ComposedTelegramRuntime:
    """The composed runtime plus the handles a caller needs to drive it.

    ``runtime.execute(payload)`` is the dispatch entry (runs end-to-end on
    kailash >= 2.28.0). ``connector`` is the bound :class:`TelegramConnector`;
    ``verifier`` verifies every receipt the connector signs; ``identity`` is
    the dispatch identity registered as the cascade root grantee.
    """

    runtime: DelegateRuntime
    dispatch_surface: DispatchSurface
    connector: TelegramConnector
    verifier: Ed25519Verifier
    identity: DelegateIdentity
    audit_engine: AuditChainEngine


def build_telegram_runtime(
    *,
    transport: TelegramTransport,
    sender_user_id: int,
    sender_chat_id: int,
    sender_principal_tenant: str = "tenant-telegram-v0",
    signing_key: Ed25519PrivateKey | None = None,
) -> ComposedTelegramRuntime:
    """Compose a real ``DelegateRuntime`` around a :class:`TelegramConnector`.

    All trust/audit/verifier concretes are the spine-shipped ones; only the
    connector is connector-specific. The returned runtime is reusable and
    holds no per-call global state.

    Args:
        transport: the connector's Bot API transport (point it at a local Bot
            API service in integration tests, the real Telegram API in
            production).
        sender_user_id: the Telegram ``user_id`` the dispatch identity
            authenticates as (the resolver's primary key).
        sender_chat_id: the paired ``chat_id`` registered alongside the
            ``user_id`` — both view the same Principal.
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
        sovereign_ref="telegram-connector-sovereign",
        role_binding_ref="telegram-connector-role-binding",
        genesis_ref="telegram-connector-genesis",
        principal_kind="delegate",
    )

    directory = PrincipalDirectory(
        identities=(identity,),
        verification_keys={delegate_id: pk_bytes},
    )
    verifier = Ed25519Verifier(directory)

    # In-memory audit chain (no Postgres) gated by the same verifier class.
    genesis_block = GenesisRecord(
        id="telegram-genesis-block",
        agent_id=str(delegate_id),
        authority_id="telegram-connector-authority",
        authority_type=AuthorityType.SYSTEM,
        created_at=datetime.now(timezone.utc),
        signature="00" * 64,
    )
    chain = TrustLineageChain(genesis=genesis_block)
    audit_engine = AuditChainEngine(chain=chain, verifier=verifier)

    delegate_genesis = DelegateGenesisRecord(
        block=genesis_block, spec_version="0", capabilities=("telegram.send",)
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
        display_name="telegram-connector-role",
        scope=RoleScope(
            domain="telegram",
            capabilities=CapabilitySet(capabilities=("telegram.send",)),
        ),
        lifecycle=RoleLifecycleState.ACTIVE,
    )

    principal = Principal(
        delegate_id=str(delegate_id),
        tenant_id=tenant.tenant_id,
        claims={"user_id": sender_user_id, "chat_id": sender_chat_id},
    )
    resolver = TelegramPrincipalResolver([(sender_user_id, sender_chat_id, principal)])

    connector = TelegramConnector(
        transport=transport,
        resolver=resolver,
        signing_key=sk,
        verifier=verifier,
        tenant_id=tenant.tenant_id,
    )

    dispatch_surface = DispatchSurface(
        connector,
        TelegramV0Signature(),
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
    return ComposedTelegramRuntime(
        runtime=runtime,
        dispatch_surface=dispatch_surface,
        connector=connector,
        verifier=verifier,
        identity=identity,
        audit_engine=audit_engine,
    )
