# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""SMTP outbound transport.

Pure transport: builds a MIME message and sends it via ``aiosmtplib`` to a
host configured entirely from the environment. No audit logic lives here — the
:class:`~delegate_connectors.email.connector.EmailConnector` wraps a
:meth:`SmtpTransport.send` call in a zero-arg async thunk and executes it under
audit (so the SMTP send is the auditable external side-effect).

Credentials are read ONLY from the environment (``EMAIL_SMTP_*``); absent
required config raises a typed :class:`SmtpConfigError` rather than silently
defaulting. Nothing in this module logs credentials.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid

import aiosmtplib

logger = logging.getLogger(__name__)

__all__ = [
    "SmtpConfig",
    "SmtpConfigError",
    "SmtpTransport",
    "SendResult",
    "OutboundMessage",
]


class SmtpConfigError(ValueError):
    """Raised when required SMTP configuration is absent from the environment."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise SmtpConfigError(
            f"{name} MUST be set in the environment (credentials are env-only; "
            "no silent default)"
        )
    return value


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    """SMTP connection coordinates, resolved from the environment.

    Host + port are required; user/password are optional (local dev servers
    like Mailpit accept unauthenticated sends). ``use_tls`` defaults to False.
    """

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    use_tls: bool = False

    @classmethod
    def from_env(cls) -> "SmtpConfig":
        """Build from ``EMAIL_SMTP_HOST/PORT/USER/PASSWORD/USE_TLS``.

        Host + port required (typed error if absent); user/password optional.
        """
        host = _require_env("EMAIL_SMTP_HOST")
        port_raw = _require_env("EMAIL_SMTP_PORT")
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise SmtpConfigError(
                f"EMAIL_SMTP_PORT MUST be an integer; got {port_raw!r}"
            ) from exc
        username = os.environ.get("EMAIL_SMTP_USER") or None
        password = os.environ.get("EMAIL_SMTP_PASSWORD") or None
        use_tls = os.environ.get("EMAIL_SMTP_USE_TLS", "false").lower() == "true"
        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
        )


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """A message to send. Pure data — no transport coupling."""

    sender: str
    recipient: str
    subject: str
    body: str
    message_id: str = field(default_factory=lambda: make_msgid())

    def to_mime(self) -> EmailMessage:
        """Construct a well-formed ``EmailMessage`` from the fields."""
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg["Subject"] = self.subject
        msg["Message-ID"] = self.message_id
        msg.set_content(self.body)
        return msg


@dataclass(frozen=True, slots=True)
class SendResult:
    """Structured outcome of an SMTP send — never a bare bool."""

    message_id: str
    accepted: bool
    recipient: str
    server_response: str


class SmtpTransport:
    """Async SMTP sender bound to an :class:`SmtpConfig`.

    Construct with an explicit config (tests) or via :meth:`from_env`
    (production). The transport holds no global state and is reusable.
    """

    def __init__(self, config: SmtpConfig) -> None:
        if not isinstance(config, SmtpConfig):
            raise TypeError(
                f"SmtpTransport.config MUST be an SmtpConfig; got {type(config).__name__}"
            )
        self._config = config

    @classmethod
    def from_env(cls) -> "SmtpTransport":
        return cls(SmtpConfig.from_env())

    @property
    def config(self) -> SmtpConfig:
        return self._config

    async def send(self, message: OutboundMessage) -> SendResult:
        """Send ``message`` over SMTP; return a structured :class:`SendResult`.

        Logs intent + outcome at INFO (never the credentials). Raises on
        transport failure — the caller (connector under audit) propagates it.
        """
        if not isinstance(message, OutboundMessage):
            raise TypeError(
                "SmtpTransport.send requires an OutboundMessage; got "
                f"{type(message).__name__}"
            )
        cfg = self._config
        logger.info(
            "email.smtp.send.start",
            extra={
                "host": cfg.host,
                "port": cfg.port,
                "recipient": message.recipient,
                "message_id": message.message_id,
            },
        )
        mime = message.to_mime()
        # aiosmtplib.send raises on hard failure; the returned errors dict maps
        # any per-recipient refusals. An empty errors dict means all accepted.
        errors, response = await aiosmtplib.send(
            mime,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password,
            use_tls=cfg.use_tls,
            start_tls=cfg.use_tls or None,
        )
        accepted = not errors
        logger.info(
            "email.smtp.send.ok",
            extra={
                "recipient": message.recipient,
                "message_id": message.message_id,
                "accepted": accepted,
            },
        )
        return SendResult(
            message_id=message.message_id,
            accepted=accepted,
            recipient=message.recipient,
            server_response=str(response),
        )
