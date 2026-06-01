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

__version__ = "0.1.1"

from delegate_connectors.whatsapp.cloud_api import (
    CloudApiConfigError,
    MessageValidationError,
    OutboundMessage,
    RateLimitedError,
    SendResult,
    WhatsAppCloudApi,
    WhatsAppCloudApiError,
    WhatsAppCloudConfig,
)
from delegate_connectors.whatsapp.compose import (
    ComposedWhatsAppRuntime,
    WhatsAppV0Signature,
    build_whatsapp_runtime,
)
from delegate_connectors.whatsapp.connector import (
    ConnectorAuthenticationError,
    InMemoryKnowledgeLedger,
    NeverRevokedChannel,
    WhatsAppConnector,
    build_action_signing_bytes,
    build_read_signing_bytes,
    verify_action_envelope,
    verify_read_receipt,
)
from delegate_connectors.whatsapp.directory import (
    ResolutionOutcome,
    UnknownSenderDisposition,
    WhatsAppPrincipalResolver,
)
from delegate_connectors.whatsapp.redaction import (
    REDACTION_SENTINEL,
    RedactionConfig,
    RedactionConfigError,
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
    # redaction (todo 02 + todo 15 startup gate)
    "redact_phone",
    "REDACTION_SENTINEL",
    "normalize_e164",
    "RedactionConfig",
    "RedactionConfigError",
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
    # Cloud API transport (todo 03)
    "WhatsAppCloudApi",
    "WhatsAppCloudConfig",
    "WhatsAppCloudApiError",
    "CloudApiConfigError",
    "RateLimitedError",
    "OutboundMessage",
    "MessageValidationError",
    "SendResult",
    # Connector core (todo 07)
    "WhatsAppConnector",
    "ConnectorAuthenticationError",
    "InMemoryKnowledgeLedger",
    "NeverRevokedChannel",
    "build_action_signing_bytes",
    "build_read_signing_bytes",
    "verify_action_envelope",
    "verify_read_receipt",
    # Runtime composition (todo 08)
    "build_whatsapp_runtime",
    "ComposedWhatsAppRuntime",
    "WhatsAppV0Signature",
]
