# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Slack connector for the Terrene Delegate substrate.

Implements the shipped ``kailash.delegate.Connector`` ABC (kailash 2.26.2) for
Slack: ``chat.postMessage`` outbound (``write``) and ``conversations.history``
inbound (``read``), authenticated against a :class:`SlackPrincipalResolver`. See
the package README + ``specs/`` in the monorepo root for the full contract.

This module exports the pure-logic foundation (message types + injection
boundary, principal resolution). The transport + connector + runtime composition
land in later shards.
"""

__version__ = "0.1.0"

from delegate_connectors.slack.directory import (
    ResolutionOutcome,
    SlackPrincipalResolver,
    UnknownSenderDisposition,
)
from delegate_connectors.slack.messages import (
    InboundSlackMessage,
    OutboundSlackMessage,
    SlackFieldError,
    normalize_slack_id,
)

__all__ = [
    "OutboundSlackMessage",
    "InboundSlackMessage",
    "SlackFieldError",
    "normalize_slack_id",
    "SlackPrincipalResolver",
    "UnknownSenderDisposition",
    "ResolutionOutcome",
    "__version__",
]
