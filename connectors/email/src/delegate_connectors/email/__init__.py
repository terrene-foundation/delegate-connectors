# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Email connector for the Terrene Delegate substrate.

Implements the shipped ``kailash.delegate.Connector`` ABC (kailash 2.26.2)
for email: SMTP outbound (``write``) and IMAP inbound (``read``), authenticated
against a ``PrincipalDirectory``. See the package README + ``specs/`` in the
monorepo root for the full contract.
"""

__version__ = "0.1.1"

from delegate_connectors.email.connector import EmailConnector
from delegate_connectors.email.directory import (
    EmailPrincipalResolver,
    UnknownSenderDisposition,
    normalize_address,
)
from delegate_connectors.email.imap import ImapTransport, InboundMessage
from delegate_connectors.email.smtp import SendResult, SmtpTransport

__all__ = [
    "EmailConnector",
    "EmailPrincipalResolver",
    "UnknownSenderDisposition",
    "normalize_address",
    "ImapTransport",
    "InboundMessage",
    "SmtpTransport",
    "SendResult",
    "__version__",
]
