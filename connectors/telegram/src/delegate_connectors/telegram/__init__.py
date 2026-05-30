# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Telegram connector for the Terrene Delegate substrate.

Implements the shipped ``kailash.delegate.Connector`` ABC (kailash 2.26.2) for
Telegram via the Bot API: ``sendMessage`` outbound (``write``) and ``getUpdates``
long-poll inbound (``read``), authenticated against a dual-keyed principal
resolver. See the package README + ``specs/`` in the monorepo root for the full
contract.

The full surface has shipped: the pure-logic foundation — principal resolution
(:mod:`delegate_connectors.telegram.directory`) and message-content validation
(:mod:`delegate_connectors.telegram.validation`) — alongside the ``httpx``-backed
Bot API transport (:mod:`delegate_connectors.telegram.transport`), the
``TelegramConnector`` itself (:mod:`delegate_connectors.telegram.connector`), and
the runtime composition (:mod:`delegate_connectors.telegram.compose`).

``__all__`` re-exports only the pure, always-importable primitives (directory +
validation) so importing the package root never forces an ``httpx`` import for
callers that only need the resolver / validators. The ``httpx``-dependent
modules are imported from their own submodules directly (e.g.
``from delegate_connectors.telegram.transport import TelegramTransport``).
"""

__version__ = "0.1.0"

from delegate_connectors.telegram.directory import (
    ResolutionOutcome,
    TelegramPrincipalResolver,
    UnknownSenderDisposition,
)
from delegate_connectors.telegram.validation import (
    MAX_TEXT_UTF16_UNITS,
    MessageValidationError,
    text_utf16_units,
    validate_chat_id,
    validate_text,
)

__all__ = [
    "__version__",
    # Principal resolution (directory.py).
    "TelegramPrincipalResolver",
    "UnknownSenderDisposition",
    "ResolutionOutcome",
    # Message-content validation (validation.py — pure, no transport).
    "MessageValidationError",
    "validate_text",
    "validate_chat_id",
    "text_utf16_units",
    "MAX_TEXT_UTF16_UNITS",
]
