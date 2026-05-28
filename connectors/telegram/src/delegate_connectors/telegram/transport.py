# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Telegram Bot API transport (``sendMessage`` outbound + ``getUpdates`` inbound).

Pure transport: an ``httpx`` async client that POSTs to ``sendMessage`` and GETs
``getUpdates`` against the configured Bot API base. No audit logic lives here —
the :class:`~delegate_connectors.telegram.connector.TelegramConnector` wraps a
:meth:`TelegramTransport.send` / :meth:`TelegramTransport.get_updates` call in a
zero-arg async thunk and executes it under audit (so the Bot API call is the
auditable external side-effect).

Credentials (the bot token + Bot API base URL) are read ONLY from the
environment (``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_API_BASE``); absent required
config raises a typed :class:`TelegramConfigError` rather than silently
defaulting. The token is part of the Bot API request URL, so this module
NEVER logs the URL or any field that contains it — log lines carry the HTTP
method + the (non-secret) ``chat_id`` only.

Construction-boundary validation of outbound message content lives in
:mod:`delegate_connectors.telegram.validation` and is invoked from
:meth:`OutboundMessage.__post_init__`, so the SINGLE boundary covers every send
route (the ``invoke`` hot path and any direct ``write`` / ``send`` call build
an ``OutboundMessage`` first; the validators raise
:class:`~delegate_connectors.telegram.validation.MessageValidationError` BEFORE
any byte transits HTTP).

Bot API ``429`` rate-limit responses are surfaced as a typed
:class:`RateLimitedError` carrying ``retry_after`` (ADR-T5) — never swallowed,
never retried in-transport; the caller decides backoff.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from delegate_connectors.telegram.validation import (
    validate_chat_id,
    validate_text,
)

logger = logging.getLogger(__name__)

__all__ = [
    "TelegramConfig",
    "TelegramConfigError",
    "TelegramTransport",
    "TelegramTransportError",
    "RateLimitedError",
    "OutboundMessage",
    "SendResult",
    "InboundUpdate",
]


class TelegramConfigError(ValueError):
    """Raised when required Telegram Bot API configuration is absent.

    Credentials are env-only; an absent ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_API_BASE``
    surfaces as this typed error rather than a silent default that would later
    produce an opaque Bot API ``401`` / ``404``.
    """


class TelegramTransportError(RuntimeError):
    """Base class for typed Bot API transport failures.

    Subclasses surface specific failure modes (``RateLimitedError`` for ``429``);
    generic non-2xx responses raise the base class with the status + body.
    """


class RateLimitedError(TelegramTransportError):
    """Raised when the Bot API responds with ``429`` + ``retry_after`` (ADR-T5).

    The typed error carries the integer ``retry_after`` seconds the API requests
    the caller to wait before retrying. Backoff is the CALLER's responsibility:
    this transport never sleeps and never retries internally, so the upstream
    audit boundary is the one that decides whether to retry the audited thunk.
    """

    def __init__(self, retry_after: int, *, description: str = "") -> None:
        self.retry_after = int(retry_after)
        self.description = description
        suffix = f" — {description}" if description else ""
        super().__init__(
            f"Telegram Bot API rate-limited (HTTP 429); retry_after="
            f"{self.retry_after}s{suffix}"
        )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise TelegramConfigError(
            f"{name} MUST be set in the environment (credentials are env-only; "
            "no silent default)"
        )
    return value


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    """Bot API connection coordinates, resolved from the environment.

    Both ``bot_token`` and ``api_base`` are required (typed error if absent).
    The ``api_base`` defaults to the public Telegram Bot API host when the env
    var is present; this dataclass holds whatever the env says, with NO silent
    default.

    The ``bot_token`` is sensitive: it is the credential the Bot API uses to
    authenticate the bot, and it appears in the request URL path. NEVER include
    ``bot_token`` (or any string derived from it, including the full request
    URL) in a log line, audit payload, or repr.
    """

    bot_token: str
    api_base: str

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        """Build from ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_API_BASE``.

        Both required (typed error if absent); no silent default for either.
        """
        bot_token = _require_env("TELEGRAM_BOT_TOKEN")
        api_base = _require_env("TELEGRAM_API_BASE")
        # Strip a single trailing slash so callers can write either form.
        if api_base.endswith("/"):
            api_base = api_base[:-1]
        return cls(bot_token=bot_token, api_base=api_base)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic, never logs the token
        # Custom repr keeps the bot_token out of any accidental log/debug print.
        return f"TelegramConfig(api_base={self.api_base!r}, bot_token=<redacted>)"


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """A message to send via ``sendMessage`` — pure data, no transport coupling.

    Content fields (``text``, ``chat_id``) are validated at construction
    (``__post_init__``) via :func:`validate_text` + :func:`validate_chat_id`,
    which reject control characters, over-length text (> 4096 UTF-16 code
    units), and a ``chat_id`` that is neither a base-10 integer nor a
    ``@channelusername`` handle. Because EVERY send route — the dispatch
    ``invoke`` hot path and any direct ``write`` / ``send`` call — builds an
    ``OutboundMessage`` first, this single boundary covers all of them: a
    crafted ``text`` / ``chat_id`` raises
    :class:`~delegate_connectors.telegram.validation.MessageValidationError`
    before any HTTP request is constructed or any byte transits the Bot API.
    """

    chat_id: int | str
    text: str

    def __post_init__(self) -> None:
        # Validate every Bot-API-bound field at the construction boundary. Raises
        # MessageValidationError; ZERO sendMessage request happens — the message
        # never even reaches to_body / TelegramTransport.send.
        validate_text(self.text)
        validate_chat_id(self.chat_id)

    def to_body(self) -> dict[str, Any]:
        """Serialize the message to the JSON body the Bot API expects."""
        return {"chat_id": self.chat_id, "text": self.text}


@dataclass(frozen=True, slots=True)
class SendResult:
    """Structured outcome of a ``sendMessage`` POST — never a bare bool.

    ``message_id`` is the Bot API's integer message identifier for the sent
    message; ``chat_id`` is the chat the message landed in. ``ok`` mirrors the
    Bot API's top-level ``"ok"`` field (always ``True`` here — non-ok responses
    raise rather than constructing a ``SendResult``).
    """

    message_id: int
    chat_id: int | str
    ok: bool


@dataclass(frozen=True, slots=True)
class InboundUpdate:
    """A normalized inbound Bot API update from a ``getUpdates`` long-poll.

    The Bot API ``Update`` shape is wide (messages, edits, channel posts,
    callback queries, ...); v0 surfaces only the ``message`` shape's fields
    most likely to enter the audit manifest. Extra fields not modeled here are
    intentionally dropped — nothing un-validated reaches the audit path.
    """

    update_id: int
    message_id: int | None
    chat_id: int | str | None
    from_user_id: int | None
    text: str | None

    @classmethod
    def from_update(cls, raw: dict[str, Any]) -> "InboundUpdate":
        """Project a Bot API ``Update`` dict into the v0 normalized shape.

        Missing or non-``message`` updates produce an :class:`InboundUpdate`
        with ``message_id`` / ``chat_id`` / ``from_user_id`` / ``text`` set to
        ``None`` (the ``update_id`` is always present in a well-formed update).
        """
        if not isinstance(raw, dict):
            raise TypeError(
                f"InboundUpdate.from_update requires a dict; got {type(raw).__name__}"
            )
        try:
            update_id = int(raw["update_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"InboundUpdate.from_update requires an integer 'update_id'; got {raw!r}"
            ) from exc
        message = raw.get("message")
        if not isinstance(message, dict):
            return cls(
                update_id=update_id,
                message_id=None,
                chat_id=None,
                from_user_id=None,
                text=None,
            )
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        return cls(
            update_id=update_id,
            message_id=(
                int(message["message_id"]) if "message_id" in message else None
            ),
            chat_id=chat.get("id") if isinstance(chat, dict) else None,
            from_user_id=(
                int(sender["id"])
                if isinstance(sender, dict) and "id" in sender
                else None
            ),
            text=message.get("text") if isinstance(message.get("text"), str) else None,
        )


class TelegramTransport:
    """Async Bot API transport bound to a :class:`TelegramConfig`.

    Construct with an explicit config (tests) or via :meth:`from_env`
    (production). The transport owns no global state beyond the optional
    injected :class:`httpx.AsyncClient`; pass a client in for tests that need
    to stub the HTTP boundary, omit it in production to let each call open a
    short-lived client.

    Timeouts default to a conservative ``30`` seconds for ``sendMessage`` and
    ``35`` seconds for ``getUpdates`` (just over the default long-poll cap so
    the server can return ``[]`` cleanly).
    """

    DEFAULT_SEND_TIMEOUT_S: float = 30.0
    DEFAULT_LONGPOLL_BUFFER_S: float = 5.0

    def __init__(
        self,
        config: TelegramConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not isinstance(config, TelegramConfig):
            raise TypeError(
                "TelegramTransport.config MUST be a TelegramConfig; got "
                f"{type(config).__name__}"
            )
        if client is not None and not isinstance(client, httpx.AsyncClient):
            raise TypeError(
                "TelegramTransport.client MUST be an httpx.AsyncClient if "
                f"supplied; got {type(client).__name__}"
            )
        self._config = config
        self._injected_client = client

    @classmethod
    def from_env(cls) -> "TelegramTransport":
        return cls(TelegramConfig.from_env())

    @property
    def config(self) -> TelegramConfig:
        return self._config

    # ── Internal helpers ────────────────────────────────────────────────

    def _endpoint(self, method: str) -> str:
        """Build the Bot API endpoint URL for ``method``.

        The full URL embeds the bot token (``/bot<token>/<method>``); this
        string is sensitive and MUST NOT be logged. Callers pass the URL to
        ``httpx`` and the response is returned without any URL appearing in
        log lines.
        """
        return f"{self._config.api_base}/bot{self._config.bot_token}/{method}"

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Convert a non-2xx Bot API response into a typed transport error.

        ``429`` is special: the Bot API returns ``retry_after`` (seconds)
        either at the top level (legacy) or inside ``parameters.retry_after``
        (current). Either shape is surfaced as :class:`RateLimitedError`; all
        other non-2xx statuses raise the generic
        :class:`TelegramTransportError` carrying the status + description.
        """
        if 200 <= response.status_code < 300:
            return
        # Try to parse the Bot API error envelope; treat any parse failure as
        # "no structured error" and fall through to the generic transport error.
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 — any json error is "no envelope"
            body = None
        description = ""
        retry_after: int | None = None
        if isinstance(body, dict):
            description = str(body.get("description") or "")
            params = body.get("parameters")
            if isinstance(params, dict) and "retry_after" in params:
                try:
                    retry_after = int(params["retry_after"])
                except (TypeError, ValueError):
                    retry_after = None
            if retry_after is None and "retry_after" in body:
                try:
                    retry_after = int(body["retry_after"])
                except (TypeError, ValueError):
                    retry_after = None
        if response.status_code == 429:
            # The Bot API guarantees retry_after on 429; absent it, default to
            # 1s so the typed error still carries an actionable value.
            raise RateLimitedError(
                retry_after if retry_after is not None else 1,
                description=description,
            )
        raise TelegramTransportError(
            f"Telegram Bot API returned HTTP {response.status_code}"
            + (f": {description}" if description else "")
        )

    async def _post_json(
        self,
        method: str,
        body: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """POST ``body`` as JSON to the Bot API ``method`` endpoint.

        Returns the parsed ``result`` object on success; raises the typed
        transport error on non-2xx. The Bot API request URL contains the bot
        token so it is NEVER logged; logging is restricted to the method name
        and (for ``sendMessage``) the non-secret ``chat_id``.
        """
        if self._injected_client is not None:
            response = await self._injected_client.post(
                self._endpoint(method), json=body, timeout=timeout
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._endpoint(method), json=body, timeout=timeout
                )
        self._raise_for_status(response)
        envelope = response.json()
        if not isinstance(envelope, dict) or not envelope.get("ok"):
            raise TelegramTransportError(
                f"Telegram Bot API {method!r} returned a non-ok envelope: "
                f"{envelope!r}"
            )
        result = envelope.get("result")
        if not isinstance(result, (dict, list)):
            raise TelegramTransportError(
                f"Telegram Bot API {method!r} 'result' MUST be a dict or list; "
                f"got {type(result).__name__}"
            )
        # Both shapes are dict-like for the post-path; sendMessage returns a dict.
        return result if isinstance(result, dict) else {"items": result}

    async def _get_json(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> list[Any] | dict[str, Any]:
        """GET the Bot API ``method`` endpoint with query ``params``.

        Returns the parsed ``result`` object on success; raises typed transport
        errors on non-2xx. ``getUpdates`` returns a list; the helper preserves
        that shape.
        """
        if self._injected_client is not None:
            response = await self._injected_client.get(
                self._endpoint(method), params=params, timeout=timeout
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self._endpoint(method), params=params, timeout=timeout
                )
        self._raise_for_status(response)
        envelope = response.json()
        if not isinstance(envelope, dict) or not envelope.get("ok"):
            raise TelegramTransportError(
                f"Telegram Bot API {method!r} returned a non-ok envelope: "
                f"{envelope!r}"
            )
        result = envelope.get("result")
        if result is None:
            raise TelegramTransportError(
                f"Telegram Bot API {method!r} response missing 'result'"
            )
        return result

    # ── Public transport API ────────────────────────────────────────────

    async def send(self, message: OutboundMessage) -> SendResult:
        """Send ``message`` via ``sendMessage``; return a structured :class:`SendResult`.

        Logs intent + outcome at INFO with method + chat_id (NEVER the URL or
        the bot token). Raises :class:`RateLimitedError` on ``429`` (the
        caller decides backoff) and :class:`TelegramTransportError` on any
        other non-2xx response.
        """
        if not isinstance(message, OutboundMessage):
            raise TypeError(
                "TelegramTransport.send requires an OutboundMessage; got "
                f"{type(message).__name__}"
            )
        logger.info(
            "telegram.sendMessage.start",
            extra={"chat_id": message.chat_id},
        )
        result = await self._post_json(
            "sendMessage",
            message.to_body(),
            timeout=self.DEFAULT_SEND_TIMEOUT_S,
        )
        try:
            message_id = int(result["message_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TelegramTransportError(
                f"sendMessage response missing integer 'message_id'; got {result!r}"
            ) from exc
        chat = result.get("chat") or {}
        chat_id = (
            chat.get("id")
            if isinstance(chat, dict) and "id" in chat
            else message.chat_id
        )
        logger.info(
            "telegram.sendMessage.ok",
            extra={"chat_id": chat_id, "message_id": message_id},
        )
        return SendResult(message_id=message_id, chat_id=chat_id, ok=True)

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
        allowed_updates: tuple[str, ...] = (),
    ) -> list[InboundUpdate]:
        """Long-poll ``getUpdates`` for new updates; return normalized inbounds.

        ``offset`` is the standard Bot API cursor (the id one greater than the
        last update the caller has already consumed). ``timeout`` is the
        long-poll seconds the Bot API holds the connection open; the HTTP-level
        timeout is set slightly above this so the server can return ``[]``
        cleanly on a quiet long-poll.
        """
        if timeout < 0:
            raise ValueError(f"getUpdates timeout MUST be >= 0; got {timeout!r}")
        params: dict[str, Any] = {"timeout": int(timeout)}
        if offset is not None:
            params["offset"] = int(offset)
        if allowed_updates:
            params["allowed_updates"] = list(allowed_updates)
        logger.info(
            "telegram.getUpdates.start",
            extra={"offset": offset, "timeout": int(timeout)},
        )
        result = await self._get_json(
            "getUpdates",
            params,
            timeout=float(timeout) + self.DEFAULT_LONGPOLL_BUFFER_S,
        )
        if not isinstance(result, list):
            raise TelegramTransportError(
                f"getUpdates 'result' MUST be a list; got {type(result).__name__}"
            )
        updates = [InboundUpdate.from_update(item) for item in result]
        logger.info(
            "telegram.getUpdates.ok",
            extra={"count": len(updates)},
        )
        return updates
