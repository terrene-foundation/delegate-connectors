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
    "HeaderInjectionError",
    "validate_header_field",
]


class SmtpConfigError(ValueError):
    """Raised when required SMTP configuration is absent from the environment."""


class HeaderInjectionError(ValueError):
    """Raised when a header-bound field carries CR/LF/NUL or control chars.

    SMTP/MIME headers are line-delimited (CRLF). An unvalidated ``to`` /
    ``subject`` / ``sender`` containing ``\\r``, ``\\n``, or ``\\x00`` lets an
    attacker inject additional headers (e.g. a blind ``Bcc:`` for silent
    exfiltration) or split the message. This typed error is raised at the
    :class:`OutboundMessage` construction boundary — BEFORE any MIME message is
    built or any byte transits SMTP — so every send route is covered.
    """


# CR, LF, and NUL are the header-injection vectors (header lines are CRLF
# delimited; NUL truncates in some C-string MTAs). We also reject every other
# C0 control char (< 0x20, except this set is already covered) and DEL (0x7f)
# in header-bound fields, plus leading/trailing whitespace which can fold
# headers or be stripped inconsistently by relays.
_FORBIDDEN_HEADER_CHARS = frozenset("\r\n\x00")
# Unicode separators some folders / serializers may treat as line breaks:
# NEL (U+0085), LINE SEPARATOR (U+2028), PARAGRAPH SEPARATOR (U+2029).
# Python's BytesGenerator does not fold on these, but rejecting them is
# defense-in-depth that future-proofs against a serializer change.
_FORBIDDEN_UNICODE_LINE_SEPARATORS = frozenset("\x85  ")


def validate_header_field(field_name: str, value: str) -> str:
    """Return ``value`` unchanged iff it is safe for a single MIME header line.

    Rejects (raising :class:`HeaderInjectionError`):

    - any ``\\r``, ``\\n``, or ``\\x00`` anywhere in the value (header injection),
    - any other C0 control character (``\\x01``–``\\x1f``) or DEL (``\\x7f``),
    - leading or trailing whitespace (header-folding / inconsistent-strip risk).

    Applied to every header-bound field (``sender``, ``to``, ``subject``) at the
    :class:`OutboundMessage` boundary so no send route can bypass it.
    """
    if not isinstance(value, str):
        raise HeaderInjectionError(
            f"header field {field_name!r} MUST be a str; got {type(value).__name__}"
        )
    for ch in value:
        if ch in _FORBIDDEN_HEADER_CHARS:
            raise HeaderInjectionError(
                f"header field {field_name!r} contains a forbidden control "
                f"character (CR/LF/NUL) — header injection rejected"
            )
        # Any remaining C0 control (0x01-0x1f) or DEL (0x7f). CR/LF/NUL are
        # already caught above; this catches VT, FF, ESC, etc.
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise HeaderInjectionError(
                f"header field {field_name!r} contains a forbidden control "
                f"character (0x{ord(ch):02x}) — header injection rejected"
            )
        # Defense-in-depth: Unicode line/paragraph separators (NEL/LS/PS).
        if ch in _FORBIDDEN_UNICODE_LINE_SEPARATORS:
            raise HeaderInjectionError(
                f"header field {field_name!r} contains a Unicode line separator "
                f"(U+{ord(ch):04X}) — header injection rejected"
            )
    if value != value.strip():
        raise HeaderInjectionError(
            f"header field {field_name!r} has leading/trailing whitespace — "
            "rejected (header-folding risk)"
        )
    return value


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
    """A message to send. Pure data — no transport coupling.

    Header-bound fields (``sender``, ``recipient``, ``subject``) are validated
    at construction (``__post_init__``) via :func:`validate_header_field`, which
    rejects CR/LF/NUL + control chars. Because EVERY send route — the dispatch
    ``invoke`` hot path and any direct ``write``/``to_mime`` call — builds an
    ``OutboundMessage`` first, this single boundary covers all of them: a
    crafted ``to``/``subject``/``sender`` raises :class:`HeaderInjectionError`
    before any MIME message is constructed or any byte transits SMTP.
    """

    sender: str
    recipient: str
    subject: str
    body: str
    message_id: str = field(default_factory=lambda: make_msgid())

    def __post_init__(self) -> None:
        # Validate every header-bound field at the construction boundary. Raises
        # HeaderInjectionError (ZERO SMTP send happens — the message never even
        # reaches to_mime / SmtpTransport.send).
        validate_header_field("sender", self.sender)
        validate_header_field("recipient", self.recipient)
        validate_header_field("subject", self.subject)

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
