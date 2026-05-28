# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Telegram connector for the Terrene Delegate substrate.

Implements the shipped ``kailash.delegate.Connector`` ABC (kailash 2.26.2) for
Telegram via the Bot API: ``sendMessage`` outbound (``write``) and ``getUpdates``
long-poll inbound (``read``), authenticated against a dual-keyed principal
resolver. See the package README + ``specs/`` in the monorepo root for the full
contract.

This package is built in waves. The pure-logic foundation — principal
resolution (:mod:`delegate_connectors.telegram.directory`) and message-content
validation (:mod:`delegate_connectors.telegram.validation`) — ships first. The
``httpx``-backed Bot API transport, the ``TelegramConnector`` itself, and the
runtime composition land in later waves; their public symbols are added to
``__all__`` as each module lands.
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
