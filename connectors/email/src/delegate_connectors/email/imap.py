# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""IMAP inbound transport.

Pure transport: connects to a host configured entirely from the environment,
fetches messages matching a search criterion via ``aioimaplib``, and parses
each raw RFC-822 message into a normalized :class:`InboundMessage`. No audit
logic lives here — the :class:`~delegate_connectors.email.connector.EmailConnector`
wraps a :meth:`ImapTransport.fetch` call in a zero-arg async thunk and executes
it under audit.

Credentials are read ONLY from the environment (``EMAIL_IMAP_*``); absent
required config raises a typed :class:`ImapConfigError`. Inbound message fields
are parsed + normalized (never raw bytes) before they leave this module, so
nothing un-validated enters the downstream audit path.
"""

from __future__ import annotations

import email
import logging
import os
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr

import aioimaplib

logger = logging.getLogger(__name__)

__all__ = [
    "ImapConfig",
    "ImapConfigError",
    "ImapTransport",
    "InboundMessage",
    "parse_rfc822",
]


class ImapConfigError(ValueError):
    """Raised when required IMAP configuration is absent from the environment."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise ImapConfigError(
            f"{name} MUST be set in the environment (credentials are env-only; "
            "no silent default)"
        )
    return value


@dataclass(frozen=True, slots=True)
class ImapConfig:
    """IMAP connection coordinates, resolved from the environment."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    use_tls: bool = False

    @classmethod
    def from_env(cls) -> "ImapConfig":
        host = _require_env("EMAIL_IMAP_HOST")
        port_raw = _require_env("EMAIL_IMAP_PORT")
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ImapConfigError(
                f"EMAIL_IMAP_PORT MUST be an integer; got {port_raw!r}"
            ) from exc
        username = os.environ.get("EMAIL_IMAP_USER") or None
        password = os.environ.get("EMAIL_IMAP_PASSWORD") or None
        use_tls = os.environ.get("EMAIL_IMAP_USE_TLS", "false").lower() == "true"
        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
        )


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A normalized inbound email — pure data, no transport coupling.

    Header values are decoded to plain ``str`` (RFC-2047 decoded); addresses
    are reduced to their bare addr-spec; the body is the text/plain part.
    """

    from_addr: str
    to_addr: str
    subject: str
    body: str
    message_id: str
    headers: dict[str, str] = field(default_factory=dict)


def _decode_header_value(raw: str | None) -> str:
    """RFC-2047-decode a header value to a plain string; '' for None."""
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (ValueError, UnicodeDecodeError):
        return raw


def _extract_body(msg: Message) -> str:
    """Return the text/plain body of ``msg`` (first such part if multipart)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.is_multipart():
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _select_rfc822_literal(lines: list) -> bytes | None:
    """Pick the RFC822 message literal from an aioimaplib FETCH response.

    The FETCH response interleaves protocol framing lines (``* 1 FETCH
    (RFC822 {NNN}``, a trailing ``)``) with the message literal blob. The
    literal is the bytes line that carries a header/body separator
    (``\\r\\n\\r\\n`` or ``\\n\\n``); among candidates the largest wins so a
    short framing line is never mistaken for the message.
    """
    best: bytes | None = None
    for line in lines:
        if not isinstance(line, (bytes, bytearray)):
            continue
        blob = bytes(line)
        if b"\r\n\r\n" in blob or b"\n\n" in blob:
            if best is None or len(blob) > len(best):
                best = blob
    return best


def parse_rfc822(raw: bytes) -> InboundMessage:
    """Parse raw RFC-822 bytes into a normalized :class:`InboundMessage`.

    Deterministic + offline — exercised directly by Tier-1 unit tests with a
    raw fixture (no network).
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError(f"parse_rfc822 requires bytes; got {type(raw).__name__}")
    msg = email.message_from_bytes(bytes(raw))
    from_addr = parseaddr(_decode_header_value(msg.get("From")))[1]
    to_addr = parseaddr(_decode_header_value(msg.get("To")))[1]
    subject = _decode_header_value(msg.get("Subject"))
    message_id = (msg.get("Message-ID") or "").strip()
    headers = {k: _decode_header_value(v) for k, v in msg.items()}
    return InboundMessage(
        from_addr=from_addr,
        to_addr=to_addr,
        subject=subject,
        body=_extract_body(msg),
        message_id=message_id,
        headers=headers,
    )


class ImapTransport:
    """Async IMAP fetcher bound to an :class:`ImapConfig`.

    Holds no global state and is reusable. ``fetch`` opens a fresh connection
    per call (v0 simplicity); production tuning is out of v0 scope.
    """

    def __init__(self, config: ImapConfig, *, mailbox: str = "INBOX") -> None:
        if not isinstance(config, ImapConfig):
            raise TypeError(
                f"ImapTransport.config MUST be an ImapConfig; got {type(config).__name__}"
            )
        self._config = config
        self._mailbox = mailbox

    @classmethod
    def from_env(cls, *, mailbox: str = "INBOX") -> "ImapTransport":
        return cls(ImapConfig.from_env(), mailbox=mailbox)

    @property
    def config(self) -> ImapConfig:
        return self._config

    async def fetch(self, criteria: str = "ALL") -> list[InboundMessage]:
        """Fetch messages matching the IMAP search ``criteria`` from the mailbox.

        Logs intent + outcome at INFO (never credentials). Raises on transport
        failure; the caller (connector under audit) propagates it.
        """
        cfg = self._config
        logger.info(
            "email.imap.fetch.start",
            extra={
                "host": cfg.host,
                "port": cfg.port,
                "mailbox": self._mailbox,
                "criteria": criteria,
            },
        )
        client = (
            aioimaplib.IMAP4_SSL(host=cfg.host, port=cfg.port)
            if cfg.use_tls
            else (aioimaplib.IMAP4(host=cfg.host, port=cfg.port))
        )
        messages: list[InboundMessage] = []
        try:
            await client.wait_hello_from_server()
            if cfg.username is not None:
                await client.login(cfg.username, cfg.password or "")
            await client.select(self._mailbox)
            search_resp = await client.search(criteria)
            if search_resp.result != "OK" or not search_resp.lines:
                logger.info("email.imap.fetch.empty", extra={"criteria": criteria})
                return messages
            # search lines: first line is a space-separated list of message ids.
            ids = search_resp.lines[0].split()
            for msg_id in ids:
                seq = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                fetch_resp = await client.fetch(seq, "(RFC822)")
                if fetch_resp.result != "OK":
                    continue
                raw = _select_rfc822_literal(fetch_resp.lines)
                if raw is not None:
                    messages.append(parse_rfc822(raw))
        finally:
            try:
                await client.logout()
            except Exception:  # pragma: no cover - cleanup best-effort
                pass
        logger.info(
            "email.imap.fetch.ok",
            extra={"criteria": criteria, "count": len(messages)},
        )
        return messages
