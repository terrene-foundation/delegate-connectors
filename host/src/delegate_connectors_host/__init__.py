# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Host-side trust surface for the Terrene Delegate connector platform.

This package is the **trusted host**. Connectors are untrusted consumers; the
host owns the things a connector must never hold:

- the credential broker + the opaque ``BoundTransport`` handle (the host owns
  ``from_env()`` and injects a non-introspectable handle — the connector never
  sees a raw secret),
- host-side receipt signing (the host holds the Ed25519 key and signs only over
  the side effect it itself brokered and observed),
- production trust-primitive concretes (``KnowledgeLedger`` / ``RevocationChannel``)
  replacing the in-connector placeholders.

The host↔connector package boundary IS the trust boundary Phase 0 establishes
(see ``workspaces/connector-platform/02-plans/01-architecture.md`` §3.5 and the
Phase-0 todo set). Conform to the frozen crypto core at
``specs/canonical-signing-bytes.md`` (v1) — never edit §1–§6.

Submodules (populated by the Phase-0 wave shards):

- ``ledger``          — production ``KnowledgeLedger`` concrete (P0-01)
- ``revocation``      — production ``RevocationChannel`` concrete (P0-02)
- ``signing_bytes``   — the shared canonical signing-bytes helpers (P0-04)
- ``bound_transport`` — the opaque non-introspectable ``BoundTransport`` (P0-06)
"""

from delegate_connectors_host.bound_transport import BoundTransport, bind_transport
from delegate_connectors_host.ledger import DurableKnowledgeLedger
from delegate_connectors_host.revocation import (
    ProductionRevocationChannel,
    StaticSignedDenylist,
    default_revocation_channel,
)

__version__ = "0.1.0"

__all__ = [
    "BoundTransport",
    "bind_transport",
    "DurableKnowledgeLedger",
    "ProductionRevocationChannel",
    "StaticSignedDenylist",
    "default_revocation_channel",
]
