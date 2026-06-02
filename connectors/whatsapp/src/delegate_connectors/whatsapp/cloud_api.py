# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""WhatsApp Cloud API transport (Meta first-party, ``httpx``).

Pure transport: an ``httpx`` async client that POSTs to the Cloud API
``/messages`` endpoint. No audit logic lives here — the
:class:`~delegate_connectors.whatsapp.connector.WhatsAppConnector` wraps a
:meth:`WhatsAppCloudApi.send` call in a zero-arg async thunk and executes it
under audit (so the Cloud API call is the auditable external side-effect).

Foundation-independence (WA-ADR-1): outbound uses the **Meta Cloud API**
first-party endpoint via the generic ``httpx`` HTTP client — there is NO
aggregator SDK (Twilio / Vonage / MessageBird) in the dependency graph, in
production code, or in tests.

Credentials (the access token + phone-number-id + Graph API version) are read
ONLY from the environment (``WHATSAPP_ACCESS_TOKEN`` + ``WHATSAPP_PHONE_NUMBER_ID``
+ ``WHATSAPP_GRAPH_VERSION``); absent required config raises a typed
:class:`CloudApiConfigError` rather than silently defaulting. The access token
is a Bearer credential — this module NEVER logs the token (or any string
derived from it), NEVER places it on a log record, and NEVER includes it in a
repr.

E.164 normalization of the recipient happens at the :class:`OutboundMessage`
construction boundary (``__post_init__`` via
:func:`~delegate_connectors.whatsapp.redaction.normalize_e164`); a value that
contains no digits raises :class:`MessageValidationError` BEFORE any byte
transits HTTP. Because EVERY send route — the dispatch ``invoke`` hot path and
any direct ``write`` / ``send`` call — builds an :class:`OutboundMessage`
first, this single boundary covers all of them.

Cloud API ``429`` rate-limit responses are surfaced as a typed
:class:`RateLimitedError` carrying ``retry_after`` (mirrors telegram ADR-T5) —
never swallowed, never retried in-transport; the caller decides backoff.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from delegate_connectors.whatsapp.redaction import (
    REDACTION_SENTINEL,
    RedactionConfig,
    normalize_e164,
)

logger = logging.getLogger(__name__)

__all__ = [
    "WhatsAppCloudConfig",
    "CloudApiConfigError",
    "WhatsAppCloudApi",
    "WhatsAppCloudApiError",
    "RateLimitedError",
    "OutboundMessage",
    "MessageValidationError",
    "SendResult",
]


# Cloud API base — published Meta Graph endpoint. The path is built as
# `{base}/v{version}/{phone_number_id}/messages` (the version + phone-number-id
# come from env-resolved config; the base is the stable public host).
CLOUD_API_BASE = "https://graph.facebook.com"


class CloudApiConfigError(ValueError):
    """Raised when required Cloud API configuration is absent at startup.

    Credentials are env-only; an absent ``WHATSAPP_ACCESS_TOKEN`` /
    ``WHATSAPP_PHONE_NUMBER_ID`` / ``WHATSAPP_GRAPH_VERSION`` surfaces as this
    typed error rather than a silent default that would later produce an
    opaque Cloud API ``401`` / ``404``. Symmetric with
    :class:`~delegate_connectors.whatsapp.webhook.WebhookConfigError` and
    :class:`~delegate_connectors.whatsapp.redaction.RedactionConfigError` —
    the three load-bearing WhatsApp credentials (Cloud API token, webhook
    secrets, PII HMAC key) refuse-on-absent with the same shape.
    """


class WhatsAppCloudApiError(RuntimeError):
    """Base class for typed Cloud API transport failures.

    Subclasses surface specific failure modes (:class:`RateLimitedError` for
    ``429``); generic non-2xx responses raise the base class with the status
    + description.
    """


class RateLimitedError(WhatsAppCloudApiError):
    """Raised when the Cloud API responds with ``429``.

    The typed error carries the integer ``retry_after`` seconds the API
    requests the caller to wait before retrying (the Cloud API surfaces it on
    the ``Retry-After`` header or inside an ``error.error_data.details``
    envelope; either shape resolves to the same typed error here). Backoff is
    the CALLER's responsibility: this transport never sleeps and never
    retries internally, so the upstream audit boundary is the one that
    decides whether to retry the audited thunk.
    """

    def __init__(self, retry_after: int, *, description: str = "") -> None:
        self.retry_after = int(retry_after)
        self.description = description
        suffix = f" — {description}" if description else ""
        super().__init__(
            f"WhatsApp Cloud API rate-limited (HTTP 429); retry_after="
            f"{self.retry_after}s{suffix}"
        )


class MessageValidationError(ValueError):
    """Raised at the :class:`OutboundMessage` construction boundary.

    A recipient that fails E.164 normalization OR a message that declares
    neither ``text`` nor ``template_name`` raises this typed error BEFORE any
    byte transits HTTP. Catching this error catches every pre-flight content
    validation failure for an outbound send.
    """


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise CloudApiConfigError(
            f"{name} MUST be set in the environment (credentials are env-only; "
            "no silent default)"
        )
    return value


@dataclass(frozen=True, slots=True)
class WhatsAppCloudConfig:
    """Cloud API connection coordinates, resolved from the environment.

    All three fields are required (typed error if absent); no silent default
    for any of them. The ``access_token`` is sensitive — a Bearer credential
    that authenticates the connector to Meta. NEVER include ``access_token``
    (or any string derived from it) in a log line, audit payload, or repr.
    """

    access_token: str
    phone_number_id: str
    graph_version: str

    @classmethod
    def from_env(cls) -> "WhatsAppCloudConfig":
        """Build from the three required ``WHATSAPP_*`` env vars.

        All three required (typed :class:`CloudApiConfigError` if absent); no
        silent default. The ``graph_version`` is stripped of any leading ``v``
        so callers can write either ``"v18.0"`` or ``"18.0"``.
        """
        access_token = _require_env("WHATSAPP_ACCESS_TOKEN")
        phone_number_id = _require_env("WHATSAPP_PHONE_NUMBER_ID")
        graph_version = _require_env("WHATSAPP_GRAPH_VERSION")
        if graph_version.startswith("v"):
            graph_version = graph_version[1:]
        return cls(
            access_token=access_token,
            phone_number_id=phone_number_id,
            graph_version=graph_version,
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic, never logs the token
        # Custom repr keeps the access_token out of any accidental log/debug print.
        return (
            f"WhatsAppCloudConfig(phone_number_id={self.phone_number_id!r}, "
            f"graph_version={self.graph_version!r}, access_token=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """A message to send via the Cloud API ``/messages`` endpoint.

    Pure data, no transport coupling. Construct with EITHER a free-form
    ``text`` body (subject to the 24h customer-service window — gated by
    :class:`~delegate_connectors.whatsapp.templates.TemplateGate` in the
    connector) OR an approved ``template_name`` (window-exempt). Exactly one
    of ``text`` / ``template_name`` MUST be set; both-or-neither raises
    :class:`MessageValidationError` at the construction boundary.

    The recipient ``to`` is normalized to bare-digit E.164 in
    ``__post_init__`` via :func:`normalize_e164`; un-normalizable values
    raise :class:`MessageValidationError` BEFORE any HTTP request is
    constructed. Because every send route builds an ``OutboundMessage``
    first, this single boundary covers them all.
    """

    to: str
    text: str | None = None
    template_name: str | None = None
    template_language: str = "en_US"

    def __post_init__(self) -> None:
        # Exactly-one-of contract: free-form text OR template, never both.
        has_text = bool(self.text)
        has_template = bool(self.template_name)
        if has_text == has_template:
            raise MessageValidationError(
                "OutboundMessage requires exactly one of 'text' or "
                "'template_name'; got both or neither"
            )
        # Normalize the recipient at the construction boundary — the resulting
        # bare-digit form is what enters the Cloud API request body. An empty
        # / un-normalizable value raises BEFORE any HTTP transit.
        try:
            normalized = normalize_e164(self.to)
        except (TypeError, ValueError) as exc:
            raise MessageValidationError(
                "OutboundMessage.to MUST be a non-empty phone identifier "
                "normalizable to E.164 digits"
            ) from exc
        object.__setattr__(self, "to", normalized)

    def to_body(self) -> dict[str, Any]:
        """Serialize the message to the Cloud API JSON body shape."""
        if self.template_name is not None:
            return {
                "messaging_product": "whatsapp",
                "to": self.to,
                "type": "template",
                "template": {
                    "name": self.template_name,
                    "language": {"code": self.template_language},
                },
            }
        # Free-form text body.
        return {
            "messaging_product": "whatsapp",
            "to": self.to,
            "type": "text",
            "text": {"body": self.text},
        }


@dataclass(frozen=True, slots=True)
class SendResult:
    """Structured outcome of a Cloud API ``/messages`` POST — never a bare bool.

    ``wamid`` is the Cloud API's ``wamid.<base64>`` message identifier for
    the sent message; ``wa_id`` is the resolved recipient identifier as
    reported by the API (the bare-digit form, identical to ``to`` in v0).
    The raw recipient phone is NEVER retained on this dataclass — the
    connector PII-redacts the recipient before signing the canonical bytes,
    and the raw value lives only in the transient outbound HTTPS body that
    is dropped after the send.
    """

    wamid: str
    wa_id: str


class WhatsAppCloudApi:
    """Async Cloud API transport bound to a :class:`WhatsAppCloudConfig`.

    Construct with an explicit config (tests) or via :meth:`from_env`
    (production). The transport owns no global state beyond the optional
    injected :class:`httpx.AsyncClient`; pass a client in for tests that need
    to stub the HTTP boundary, omit it in production to let each call open a
    short-lived client.

    Timeouts default to a conservative ``30`` seconds for ``/messages``.
    """

    DEFAULT_SEND_TIMEOUT_S: float = 30.0

    def __init__(
        self,
        config: WhatsAppCloudConfig,
        *,
        client: httpx.AsyncClient | None = None,
        redaction_config: RedactionConfig | None = None,
    ) -> None:
        if not isinstance(
            config, WhatsAppCloudConfig
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "WhatsAppCloudApi.config MUST be a WhatsAppCloudConfig; got "
                f"{type(config).__name__}"
            )
        if client is not None and not isinstance(
            client, httpx.AsyncClient
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "WhatsAppCloudApi.client MUST be an httpx.AsyncClient if "
                f"supplied; got {type(client).__name__}"
            )
        self._config = config
        self._injected_client = client
        # The STARTUP-validated redaction config carrying the PII-HMAC key,
        # threaded into the log-line redaction so `send` NEVER re-reads
        # os.environ per message (P0-07). When omitted the transport resolves
        # it once from the environment HERE (startup-loud, run once at
        # construction rather than per send).
        self._redaction_config = (
            redaction_config
            if redaction_config is not None
            else RedactionConfig.from_env()
        )

    @classmethod
    def from_env(cls) -> "WhatsAppCloudApi":
        return cls(WhatsAppCloudConfig.from_env())

    @property
    def config(self) -> WhatsAppCloudConfig:
        return self._config

    # ── Internal helpers ────────────────────────────────────────────────

    def _endpoint(self) -> str:
        """Build the ``/messages`` endpoint URL for the configured phone number."""
        return (
            f"{CLOUD_API_BASE}/v{self._config.graph_version}/"
            f"{self._config.phone_number_id}/messages"
        )

    def _headers(self) -> dict[str, str]:
        """Build the request headers including the ``Authorization`` Bearer.

        The Authorization header carries the access token; it is built per
        call and NEVER stored on a long-lived field that might appear in a
        repr or log dump.
        """
        return {
            "Authorization": f"Bearer {self._config.access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Convert a non-2xx Cloud API response into a typed transport error.

        ``429`` is special: the Cloud API may surface ``retry_after`` on a
        ``Retry-After`` header OR inside the ``error.error_data`` envelope.
        Either shape resolves to :class:`RateLimitedError`; all other non-2xx
        statuses raise :class:`WhatsAppCloudApiError` carrying the status +
        description. Response bodies are NEVER logged verbatim (they may
        echo recipient PII); the typed error message includes only the
        Cloud API's structured description string.
        """
        if 200 <= response.status_code < 300:
            return
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 — any json error is "no envelope"
            body = None
        description = ""
        retry_after: int | None = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                description = str(error.get("message") or "")
                error_data = error.get("error_data")
                if isinstance(error_data, dict) and "details" in error_data:
                    details = str(error_data.get("details") or "")
                    if details:
                        description = (
                            f"{description}: {details}" if description else details
                        )
        # Honor the standard ``Retry-After`` header first; fall back to the
        # error envelope if the header is missing.
        header_retry = response.headers.get("Retry-After")
        if header_retry is not None:
            try:
                retry_after = int(header_retry)
            except (TypeError, ValueError):
                retry_after = None
        if response.status_code == 429:
            raise RateLimitedError(
                retry_after if retry_after is not None else 1,
                description=description,
            )
        raise WhatsAppCloudApiError(
            f"WhatsApp Cloud API returned HTTP {response.status_code}"
            + (f": {description}" if description else "")
        )

    async def _post_json(
        self,
        body: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """POST ``body`` as JSON to the Cloud API ``/messages`` endpoint.

        Returns the parsed response object on success; raises the typed
        transport error on non-2xx. The Bearer header carries the access
        token so its construction site is the ONLY place the token appears
        in this module — logging is restricted to the HTTP method and a
        redacted recipient token.
        """
        url = self._endpoint()
        headers = self._headers()
        if self._injected_client is not None:
            response = await self._injected_client.post(
                url, headers=headers, json=body, timeout=timeout
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers=headers, json=body, timeout=timeout
                )
        self._raise_for_status(response)
        try:
            envelope = response.json()
        except Exception as exc:  # noqa: BLE001 — surface as typed transport error
            raise WhatsAppCloudApiError(
                "WhatsApp Cloud API '/messages' returned a non-JSON response"
            ) from exc
        if not isinstance(envelope, dict):
            raise WhatsAppCloudApiError(
                "WhatsApp Cloud API '/messages' response MUST be a JSON object; "
                f"got {type(envelope).__name__}"
            )
        return envelope

    # ── Public transport API ────────────────────────────────────────────

    async def send(self, message: OutboundMessage) -> SendResult:
        """Send ``message`` via the Cloud API; return a structured :class:`SendResult`.

        Logs intent + outcome at INFO with the HTTP method + a PII-redacted
        recipient token (NEVER the raw E.164, NEVER the access token, NEVER
        the full request URL). Raises :class:`RateLimitedError` on ``429``
        (the caller decides backoff) and :class:`WhatsAppCloudApiError` on
        any other non-2xx response. The Cloud API response envelope shape is

            {
              "messaging_product": "whatsapp",
              "contacts": [{"input": "...", "wa_id": "..."}],
              "messages": [{"id": "wamid.<base64>"}]
            }

        — ``messages[0].id`` is the WhatsApp message id (``wamid``);
        ``contacts[0].wa_id`` is the resolved recipient. Both fields are
        required; either missing raises :class:`WhatsAppCloudApiError`.
        """
        if not isinstance(
            message, OutboundMessage
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "WhatsAppCloudApi.send requires an OutboundMessage; got "
                f"{type(message).__name__}"
            )
        # Redact the recipient for the log line. The raw E.164 NEVER appears
        # in a log record on the happy path — the only place the raw bytes
        # live is in the request body about to transit HTTPS, dropped after
        # the send completes.
        redacted_to = self._redaction_config.redact(message.to)
        logger.info(
            "whatsapp.cloud_api.messages.start",
            extra={"to_redacted": redacted_to},
        )
        envelope = await self._post_json(
            message.to_body(),
            timeout=self.DEFAULT_SEND_TIMEOUT_S,
        )
        messages = envelope.get("messages")
        contacts = envelope.get("contacts")
        if (
            not isinstance(messages, list)
            or not messages
            or not isinstance(messages[0], dict)
        ):
            raise WhatsAppCloudApiError(
                "Cloud API '/messages' response missing 'messages[0]'"
            )
        wamid = messages[0].get("id")
        if not isinstance(wamid, str) or not wamid:
            raise WhatsAppCloudApiError(
                "Cloud API '/messages' response 'messages[0].id' MUST be a "
                "non-empty string"
            )
        # contacts[0].wa_id is normatively present on a successful send; fall
        # back to the request's bare-digit `to` if the API omitted it (the
        # request's `to` was already invariant-normalized).
        resolved_wa_id: str = message.to
        if (
            isinstance(contacts, list)
            and contacts
            and isinstance(contacts[0], dict)
            and isinstance(contacts[0].get("wa_id"), str)
            and contacts[0].get("wa_id")
        ):
            resolved_wa_id = str(contacts[0]["wa_id"])
        # Log on the redacted token of the RESOLVED wa_id (not the request
        # `to`) so the log surface mirrors what the Cloud API actually
        # delivered to. Defensive: if redaction yields the sentinel, log it
        # — surfacing the sentinel is the documented failure mode.
        logger.info(
            "whatsapp.cloud_api.messages.ok",
            extra={
                "wamid": wamid,
                "wa_id_redacted": (
                    self._redaction_config.redact(resolved_wa_id)
                    if resolved_wa_id
                    else REDACTION_SENTINEL
                ),
            },
        )
        return SendResult(wamid=wamid, wa_id=resolved_wa_id)
