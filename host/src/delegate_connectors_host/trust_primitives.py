# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Canonical host trust-primitive bindings (Phase-0, P0-10a; folds former P0-03).

Phase 0 keeps exactly ONE already-production spine trust primitive as the host's
canonical authentication verifier: the SDK :class:`kailash.delegate.verifier.
Ed25519Verifier`. This module is the single canonical binding the
``connector_builder`` factory IMPORTS — so there is no local ``AuthVerifier``
placeholder class anywhere in the host package, and the binding is consumed (by
the factory), never an imported-by-nobody orphan.

Why an alias and not a re-implementation
========================================
``specs sdk_provided_vs_local`` records that ``AuthVerifier`` is the one trust
primitive Phase 0 does NOT re-build locally (unlike the ``KnowledgeLedger`` and
``RevocationChannel`` concretes, which had no shipped backend). The SDK ships a
real, production ``Ed25519Verifier`` with the exact
``verify(canonical_bytes, signature, signer_delegate_id) -> bool`` contract the
host needs; the host's job is to PIN it as the canonical binding, not to wrap or
shadow it. ``AuthVerifier`` is therefore a name-level alias — every host call site
that means "the canonical authentication verifier" references ``AuthVerifier``,
and it resolves to the one SDK class.
"""

from __future__ import annotations

from kailash.delegate.verifier import Ed25519Verifier

__all__ = ["AuthVerifier"]


# The canonical host authentication verifier. Phase 0 pins the SDK's shipped
# Ed25519Verifier as the single AuthVerifier binding (no local placeholder); the
# connector_builder factory imports THIS name as the one consumer.
AuthVerifier = Ed25519Verifier
