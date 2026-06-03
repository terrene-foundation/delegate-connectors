# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Shared canonical signing-bytes helpers for the Delegate connectors (P0-04).

These four helpers were duplicated VERBATIM across every connector's
``connector.py`` (email / slack / telegram / whatsapp). They are the
conformance-frozen producers of canonical signing bytes — they call
:func:`kailash.trust._json.canonical_json_dumps` and conform to
``specs/canonical-signing-bytes.md`` §1–§6 (FROZEN v1). The extraction is
behavior-preserving: the canonical bytes produced here are byte-for-byte
identical to the per-connector copies they replace.

- :func:`build_action_signing_bytes` — write signing bytes (binds the full
  receipt identity: payload + signer + action id + observed_at).
- :func:`build_read_signing_bytes` — read signing bytes (binds manifest +
  attester + read id + observed_at).
- :func:`verify_action_envelope` — re-derives the action bytes from the
  envelope's own identity fields and verifies the Ed25519 signature.
- :func:`verify_read_receipt` — re-derives the read bytes from the receipt's
  own identity fields and verifies the attestation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from kailash.delegate.dispatch import AttestedReadReceipt, SignedActionEnvelope
from kailash.delegate.verifier import Ed25519Verifier
from kailash.trust._json import canonical_json_dumps

from delegate_connectors_host.canonical_domain import assert_canonical_signing_domain

__all__ = [
    "build_action_signing_bytes",
    "build_read_signing_bytes",
    "verify_action_envelope",
    "verify_read_receipt",
]


def build_action_signing_bytes(
    payload: dict[str, Any],
    *,
    signer_delegate_id: str,
    action_id: str,
    observed_at: str,
) -> bytes:
    """Canonical signing bytes for a write — binds the FULL receipt identity.

    Signs over ``{payload, signer_delegate_id, action_id, observed_at}`` (not the
    bare ``payload``), so two writes with an identical payload produce DIFFERENT
    signed bytes (distinct ``action_id`` + ``observed_at``) and the signer /
    action id / observation time are cryptographically bound — closing the
    replay/forge surface where same-payload receipts were byte-identical.

    Rejects (``NonConformantPayloadError``) a ``payload`` carrying a value the
    frozen v1 wire form cannot represent interoperably — a float / NaN / Infinity,
    an integer outside ``[-(2^53-1), 2^53-1]``, a non-string object key, or a lone
    surrogate — BEFORE signing, per ``specs/canonical-signing-bytes.md`` §1.2–§1.5
    + §5 (the producer-side reject suite enforced at the connector boundary §1.4).
    """
    # Snapshot once, then validate + encode the SAME snapshot: the bytes we sign
    # are provably the bytes we validated (no validate-then-encode window where a
    # shared mutable nested container could change between the two reads).
    payload = deepcopy(payload)
    assert_canonical_signing_domain(payload)
    return canonical_json_dumps(
        {
            "payload": payload,
            "signer_delegate_id": signer_delegate_id,
            "action_id": action_id,
            "observed_at": observed_at,
        }
    ).encode("utf-8")


def build_read_signing_bytes(
    manifest: dict[str, Any],
    *,
    attester_delegate_id: str,
    read_id: str,
    observed_at: str,
) -> bytes:
    """Canonical signing bytes for a read — binds the FULL receipt identity.

    Signs over ``{manifest, attester_delegate_id, read_id, observed_at}`` (not the
    bare ``manifest``), so the attester / read id / observation time are bound
    into the attestation.

    Rejects (``NonConformantPayloadError``) a ``manifest`` carrying a value the
    frozen v1 wire form cannot represent interoperably (float / NaN / Infinity,
    out-of-range integer, non-string object key, lone surrogate) BEFORE signing,
    per ``specs/canonical-signing-bytes.md`` §1.2–§1.5 + §5.
    """
    # Snapshot once, then validate + encode the SAME snapshot (see
    # build_action_signing_bytes for the validate-then-encode rationale).
    manifest = deepcopy(manifest)
    assert_canonical_signing_domain(manifest)
    return canonical_json_dumps(
        {
            "manifest": manifest,
            "attester_delegate_id": attester_delegate_id,
            "read_id": read_id,
            "observed_at": observed_at,
        }
    ).encode("utf-8")


def verify_action_envelope(
    envelope: SignedActionEnvelope,
    verifier: Ed25519Verifier,
    *,
    observed_at: str,
) -> bool:
    """Verify a write envelope: signature valid AND identity-bound bytes match.

    Re-derives the canonical signing bytes from the envelope's OWN identity
    fields (``payload`` + ``signer_delegate_id`` + ``action_id`` + the supplied
    ``observed_at``) and checks (a) the re-derived bytes equal the signed
    ``envelope.canonical_bytes`` AND (b) the Ed25519 signature verifies. Tamper
    with ``signer_delegate_id`` / ``action_id`` / ``payload`` and the re-derived
    bytes diverge from the signed bytes, so verification fails.
    """
    expected = build_action_signing_bytes(
        dict(envelope.payload),
        signer_delegate_id=envelope.signer_delegate_id,
        action_id=str(envelope.action_id),
        observed_at=observed_at,
    )
    if expected != envelope.canonical_bytes:
        return False
    return verifier.verify(
        envelope.canonical_bytes,
        envelope.signature,
        envelope.signer_delegate_id,
    )


def verify_read_receipt(
    receipt: AttestedReadReceipt,
    manifest: dict[str, Any],
    verifier: Ed25519Verifier,
) -> bool:
    """Verify a read receipt: signature valid AND identity-bound bytes match.

    Re-derives the canonical signing bytes from the receipt's OWN identity
    fields (``manifest`` + ``attester_delegate_id`` + ``read_id`` +
    ``observed_at``) and checks the re-derived bytes equal the signed
    ``receipt.canonical_bytes`` AND the attestation verifies.
    """
    expected = build_read_signing_bytes(
        manifest,
        attester_delegate_id=receipt.attester_delegate_id,
        read_id=str(receipt.read_id),
        observed_at=receipt.observed_at.isoformat(timespec="microseconds"),
    )
    if expected != receipt.canonical_bytes:
        return False
    return verifier.verify(
        receipt.canonical_bytes,
        receipt.attestation,
        receipt.attester_delegate_id,
    )
