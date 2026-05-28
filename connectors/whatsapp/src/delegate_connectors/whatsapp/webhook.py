# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Webhook ingest protocol + in-process buffer (the security boundary).

WhatsApp is webhook-push only; the shipped ``read`` thunk is one-shot/pull. v0
owns the ingest PROTOCOL + an in-process buffer — NOT a running HTTP server
(owning the public TLS-terminated socket is a deploy concern, WA-ADR-2).

The ingest protocol is the security boundary that keeps unverified payloads out
of the audit path:

- Verify-token handshake: echo ``hub.challenge`` ONLY when ``hub.verify_token``
  matches ``WHATSAPP_WEBHOOK_VERIFY_TOKEN`` under a constant-time compare.
- ``X-Hub-Signature-256`` HMAC over the RAW request body (app secret from
  ``WHATSAPP_APP_SECRET``), constant-time compare. A payload that fails the HMAC
  is REFUSED and NEVER buffered, NEVER audited.
- Envelope parse: ``entry[].changes[].value.messages[]`` → a normalized
  :class:`InboundMessage`. The sender phone / ``wa_id`` is PII-redacted (todo 02)
  before the message enters the buffer — the raw number never lands in a buffered
  record.

Each verified inbound feeds an optional per-recipient last-inbound timestamp sink
(the window tracker, todo 06) so the 24h-window gate has its data source.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field

from delegate_connectors.whatsapp.redaction import redact_phone

logger = logging.getLogger(__name__)

__all__ = [
    "WebhookConfig",
    "WebhookConfigError",
    "InboundMessage",
    "WebhookIngest",
    "verify_signature",
    "verify_token_challenge",
    "parse_inbound_envelope",
    "SIGNATURE_HEADER",
]

#: The header WhatsApp signs the raw body under (lowercased for case-insensitive
#: matching by callers).
SIGNATURE_HEADER = "x-hub-signature-256"


class WebhookConfigError(ValueError):
    """Raised when required webhook configuration is absent from the environment."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise WebhookConfigError(
            f"{name} MUST be set in the environment (credentials are env-only; "
            "no silent default)"
        )
    return value


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    """Webhook verification coordinates, resolved from the environment."""

    app_secret: str
    verify_token: str

    @classmethod
    def from_env(cls) -> "WebhookConfig":
        return cls(
            app_secret=_require_env("WHATSAPP_APP_SECRET"),
            verify_token=_require_env("WHATSAPP_WEBHOOK_VERIFY_TOKEN"),
        )


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A normalized inbound WhatsApp message — pure data, no transport coupling.

    The sender is stored ONLY as the PII-redacted token (:attr:`sender_redacted`,
    a ``wa:<8-hex>`` value); the raw ``wa_id`` is never retained on a buffered
    record. :attr:`sender_e164_normalized` is the bare-digit form used for window
    tracking (todo 06) — also derived, never the surface-formatted raw input.
    """

    sender_redacted: str
    sender_e164_normalized: str
    message_type: str
    text: str
    timestamp: str
    message_id: str
    headers: dict[str, str] = field(default_factory=dict)


def verify_token_challenge(params: dict[str, str], config: WebhookConfig) -> str | None:
    """Echo ``hub.challenge`` iff ``hub.verify_token`` matches, constant-time.

    Returns the challenge string on a matching verify-token + a ``subscribe``
    mode; returns ``None`` (no echo) on any mismatch. The compare uses
    :func:`hmac.compare_digest` so it does not leak via timing.
    """
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge")
    token_ok = hmac.compare_digest(token, config.verify_token)
    if mode == "subscribe" and token_ok and challenge is not None:
        return challenge
    return None


def verify_signature(
    raw_body: bytes, signature_header: str | None, config: WebhookConfig
) -> bool:
    """Constant-time verify of ``X-Hub-Signature-256`` over the RAW body.

    ``signature_header`` is the ``sha256=<hex>`` value WhatsApp sends. The HMAC is
    computed over the EXACT raw bytes received (never a re-serialized form) keyed
    by the app secret; the compare is constant-time. Returns ``True`` only on a
    valid signature.
    """
    if not isinstance(raw_body, (bytes, bytearray)):
        raise TypeError(
            f"verify_signature requires bytes for raw_body; got {type(raw_body).__name__}"
        )
    if not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    provided = signature_header[len(prefix) :]
    expected = hmac.new(
        config.app_secret.encode("utf-8"), bytes(raw_body), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(provided, expected)


def parse_inbound_envelope(payload: dict) -> list[InboundMessage]:
    """Parse a verified webhook payload into normalized inbound messages.

    Walks ``entry[].changes[].value.messages[]``. The sender ``wa_id`` (or
    ``from``) is PII-redacted before it enters any returned record. Malformed or
    statuses-only payloads (no ``messages``) yield an empty list — never an
    exception that would surface a raw number.
    """
    messages: list[InboundMessage] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for msg in value.get("messages", []) or []:
                raw_sender = msg.get("from") or msg.get("wa_id") or ""
                msg_type = msg.get("type", "")
                text = ""
                if msg_type == "text":
                    text = (msg.get("text") or {}).get("body", "")
                messages.append(
                    InboundMessage(
                        sender_redacted=redact_phone(raw_sender),
                        sender_e164_normalized=_safe_normalize(raw_sender),
                        message_type=msg_type,
                        text=text,
                        timestamp=str(msg.get("timestamp", "")),
                        message_id=str(msg.get("id", "")),
                    )
                )
    return messages


def _safe_normalize(raw: str) -> str:
    """Normalize without leaking — returns '' rather than raising on bad input."""
    from delegate_connectors.whatsapp.redaction import normalize_e164

    try:
        return normalize_e164(raw)
    except (TypeError, ValueError):
        return ""


class WebhookIngest:
    """In-process ingest buffer the ``read`` thunk drains (WA-ADR-2).

    :meth:`ingest` is the verified-entry boundary: it verifies the
    ``X-Hub-Signature-256`` HMAC over the raw body FIRST and refuses (never
    buffers, never audits) any payload that fails. Verified inbound messages are
    appended to an in-process FIFO buffer and each feeds the optional
    ``window_sink`` (the window tracker, todo 06) keyed by the normalized E.164.

    The buffer is a plain ``list`` drained FIFO by :meth:`drain_one` /
    :meth:`drain_all`; no running HTTP server is owned here (out of v0 scope).
    """

    def __init__(
        self,
        config: WebhookConfig,
        *,
        window_sink: Callable[[str, str], None] | None = None,
    ) -> None:
        if not isinstance(
            config, WebhookConfig
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                f"WebhookIngest.config MUST be a WebhookConfig; got {type(config).__name__}"
            )
        self._config = config
        self._buffer: list[InboundMessage] = []
        # window_sink(normalized_e164, timestamp) records the last-inbound time
        # for the 24h customer-service window gate (todo 06).
        self._window_sink = window_sink

    @classmethod
    def from_env(
        cls, *, window_sink: Callable[[str, str], None] | None = None
    ) -> "WebhookIngest":
        return cls(WebhookConfig.from_env(), window_sink=window_sink)

    @property
    def config(self) -> WebhookConfig:
        return self._config

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    def ingest(self, raw_body: bytes, signature_header: str | None) -> int:
        """Verify + buffer an inbound webhook delivery.

        Returns the number of messages buffered. A payload whose HMAC does not
        verify is REFUSED: it returns ``0``, nothing is buffered, and nothing is
        audited (the verification is the security boundary). A verified payload
        with no ``messages`` (e.g. a statuses callback) also returns ``0`` but is
        not a refusal.
        """
        if not verify_signature(raw_body, signature_header, self._config):
            # Refused at the boundary — never buffered, never audited. Log the
            # rejection WITHOUT any payload bytes (they are unverified + may carry
            # PII).
            logger.warning("whatsapp.webhook.signature_invalid")
            return 0
        try:
            payload = json.loads(bytes(raw_body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("whatsapp.webhook.payload_unparseable")
            return 0
        messages = parse_inbound_envelope(payload)
        for message in messages:
            self._buffer.append(message)
            if self._window_sink is not None and message.sender_e164_normalized:
                self._window_sink(message.sender_e164_normalized, message.timestamp)
        logger.info("whatsapp.webhook.ingest.ok", extra={"count": len(messages)})
        return len(messages)

    def drain_one(self) -> InboundMessage | None:
        """Pop and return the oldest buffered message, or ``None`` if empty.

        This is the one-shot drain the ``read`` thunk calls (todo 07).
        """
        if not self._buffer:
            return None
        return self._buffer.pop(0)

    def drain_all(self) -> list[InboundMessage]:
        """Pop and return all buffered messages in FIFO order, emptying the buffer."""
        drained = list(self._buffer)
        self._buffer.clear()
        return drained
