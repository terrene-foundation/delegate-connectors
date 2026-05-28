# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""WhatsApp connector for the Terrene Delegate substrate.

Targets the shipped ``kailash.delegate.Connector`` ABC (kailash 2.26.2) for
WhatsApp over the first-party Meta Cloud API. This package's v0 (Wave 1) ships
the pure-logic / stdlib-crypto security foundation — PII redaction, principal
resolution, the webhook ingest protocol + buffer, and the outbound template /
service-window gate. The Cloud API transport, the connector class, and runtime
composition land in later waves. See the package README + ``specs/`` (and the
v0 contract in ``workspaces/whatsapp/02-plans/``) for the full design.
"""

__version__ = "0.1.0"

from delegate_connectors.whatsapp.directory import (
    ResolutionOutcome,
    UnknownSenderDisposition,
    WhatsAppPrincipalResolver,
)
from delegate_connectors.whatsapp.redaction import (
    REDACTION_SENTINEL,
    normalize_e164,
    redact_phone,
)
from delegate_connectors.whatsapp.templates import (
    OutsideServiceWindowError,
    ServiceWindowTracker,
    TemplateGate,
    TemplateNotApprovedError,
    WhatsAppRejectError,
)
from delegate_connectors.whatsapp.webhook import (
    InboundMessage,
    WebhookConfig,
    WebhookConfigError,
    WebhookIngest,
    parse_inbound_envelope,
    verify_signature,
    verify_token_challenge,
)

__all__ = [
    "__version__",
    # redaction (todo 02)
    "redact_phone",
    "REDACTION_SENTINEL",
    "normalize_e164",
    # directory (todo 04)
    "WhatsAppPrincipalResolver",
    "UnknownSenderDisposition",
    "ResolutionOutcome",
    # webhook ingest (todo 05)
    "WebhookIngest",
    "WebhookConfig",
    "WebhookConfigError",
    "InboundMessage",
    "verify_signature",
    "verify_token_challenge",
    "parse_inbound_envelope",
    # template / window gate (todo 06)
    "TemplateGate",
    "ServiceWindowTracker",
    "WhatsAppRejectError",
    "OutsideServiceWindowError",
    "TemplateNotApprovedError",
]
