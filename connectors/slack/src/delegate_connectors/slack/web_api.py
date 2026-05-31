# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Slack Web API transport — ``chat.postMessage`` outbound + ``conversations.history`` inbound.

Pure transport: builds Slack Web API calls via ``slack_sdk.web.async_client.AsyncWebClient``
and a base URL + bot token resolved entirely from the environment. No audit logic
lives here — the :class:`~delegate_connectors.slack.connector.SlackConnector`
wraps a :meth:`SlackTransport.post_message` / :meth:`SlackTransport.history` call
in a zero-arg async thunk and executes it under audit (so the Slack API call is
the auditable external side-effect).

Credentials are read ONLY from the environment (``SLACK_BOT_TOKEN``); absent
required config raises a typed :class:`SlackWebConfigError` rather than silently
defaulting. ``SLACK_API_BASE_URL`` overrides the default Slack API base URL so
the Tier-2 mock-server container can stand in for the live Slack API at the same
seam the live transport uses. Nothing in this module logs credentials.

``AsyncWebClient`` is imported LAZILY (inside the constructor / build helpers) so
this module imports cleanly even when ``aiohttp`` (an ``AsyncWebClient`` dep) is
absent from the environment. Tier-1 unit tests stub the SDK boundary by injecting
a fake client into :class:`SlackTransport` via the ``_client`` constructor kwarg
(or by patching :meth:`SlackTransport._build_client`) — neither path imports
``aiohttp``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from delegate_connectors.slack.messages import (
    InboundSlackMessage,
    OutboundSlackMessage,
    normalize_slack_id,
)

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

__all__ = [
    "SlackWebConfig",
    "SlackWebConfigError",
    "SlackTransportError",
    "SlackTransport",
    "PostResult",
]

# Slack's documented Web API base URL. ``SLACK_API_BASE_URL`` overrides this so
# a Tier-2 mock-server container can intercept the same SDK call path. Trailing
# slash matches ``AsyncWebClient``'s default (``https://slack.com/api/``).
_DEFAULT_SLACK_API_BASE_URL = "https://slack.com/api/"


class SlackWebConfigError(ValueError):
    """Raised when required Slack Web API configuration is absent from the environment."""


class SlackTransportError(RuntimeError):
    """Raised when ``chat.postMessage`` is rejected by Slack at the API level.

    Slack returns ``{"ok": false, "error": "<code>"}`` at HTTP 200 when a post
    is rejected (``channel_not_found``, ``not_in_channel``, ``is_archived`` …).
    The transport MUST raise on that envelope so the connector under audit
    aborts BEFORE signing — a signed envelope must only ever attest a send that
    actually occurred. Carries Slack's ``error`` code; never the bot token.
    """


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise SlackWebConfigError(
            f"{name} MUST be set in the environment (credentials are env-only; "
            "no silent default)"
        )
    return value


@dataclass(frozen=True, slots=True)
class SlackWebConfig:
    """Slack Web API connection coordinates, resolved from the environment.

    ``bot_token`` is the ``xoxb-…`` bot token (required; env-only). ``base_url``
    overrides the default Slack Web API base URL — supplied by the Tier-2 mock
    container in test environments, omitted in production so the SDK's default
    Slack URL is used.
    """

    bot_token: str
    base_url: str = _DEFAULT_SLACK_API_BASE_URL

    @classmethod
    def from_env(cls) -> "SlackWebConfig":
        """Build from ``SLACK_BOT_TOKEN`` + optional ``SLACK_API_BASE_URL``.

        ``SLACK_BOT_TOKEN`` required (typed error if absent — no silent default).
        ``SLACK_API_BASE_URL``, when set, retargets the ``AsyncWebClient`` base
        URL so a Tier-2 mock container intercepts the call. Otherwise the
        Slack-default base URL is used.
        """
        bot_token = _require_env("SLACK_BOT_TOKEN")
        base_url = os.environ.get("SLACK_API_BASE_URL") or _DEFAULT_SLACK_API_BASE_URL
        return cls(bot_token=bot_token, base_url=base_url)


@dataclass(frozen=True, slots=True)
class PostResult:
    """Structured outcome of a ``chat.postMessage`` — never a bare bool.

    ``ok`` mirrors Slack's documented ``response["ok"]`` flag; ``ts`` is the
    Slack message timestamp id (the per-message canonical id); ``channel`` is
    the channel id the post landed in (Slack echoes it back even when the caller
    supplied a channel name).
    """

    ok: bool
    ts: str
    channel: str


def _build_async_web_client(*, token: str, base_url: str) -> "AsyncWebClient":
    """Lazily import + construct an ``AsyncWebClient``.

    Imported inside the function body (NOT at module top) so this module imports
    cleanly under Tier-1 conditions where ``aiohttp`` (an ``AsyncWebClient``
    dependency) is absent. Tests stub the SDK boundary by injecting a fake
    client into :class:`SlackTransport` via the ``_client`` constructor kwarg.
    """
    from slack_sdk.web.async_client import AsyncWebClient  # local import

    return AsyncWebClient(token=token, base_url=base_url)


class SlackTransport:
    """Async Slack Web API transport bound to a :class:`SlackWebConfig`.

    Construct with an explicit config (tests / production both use the same
    constructor) or via :meth:`from_env`. The transport holds no global state
    and is reusable.

    For Tier-1 tests, pass ``_client=<fake>`` to bypass the ``AsyncWebClient``
    construction (and therefore the ``aiohttp`` dependency); the fake MUST
    expose ``chat_postMessage(channel=..., text=...) -> dict`` and
    ``conversations_history(channel=..., limit=...) -> dict`` as awaitables (the
    same shape ``AsyncWebClient`` exposes).
    """

    def __init__(
        self,
        config: SlackWebConfig,
        *,
        _client: "AsyncWebClient | None" = None,
    ) -> None:
        if not isinstance(
            config, SlackWebConfig
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "SlackTransport.config MUST be a SlackWebConfig; got "
                f"{type(config).__name__}"
            )
        self._config = config
        # Eagerly build the client when not test-injected so a misconfigured
        # base URL surfaces at construction (not on first call). Lazy SDK import
        # keeps Tier-1 import clean (see _build_async_web_client docstring).
        self._client = (
            _client
            if _client is not None
            else _build_async_web_client(
                token=config.bot_token, base_url=config.base_url
            )
        )

    @classmethod
    def from_env(cls) -> "SlackTransport":
        return cls(SlackWebConfig.from_env())

    @property
    def config(self) -> SlackWebConfig:
        return self._config

    async def post_message(self, message: OutboundSlackMessage) -> PostResult:
        """Post ``message`` via ``chat.postMessage``; return a structured :class:`PostResult`.

        ``message`` carries the already-validated ``channel`` + the already
        mrkdwn-escaped ``text`` (the :class:`OutboundSlackMessage` construction
        boundary handles both). Logs intent + outcome at INFO (never the token).
        Raises :class:`SlackTransportError` when Slack rejects the post at the
        API level (``response["ok"] == False``) OR when ``ok`` is true but the
        message timestamp (``ts``) is absent — either case means no addressable
        message was delivered. The connector under audit propagates the raise so
        it aborts BEFORE signing; a signed envelope must never attest a send the
        API did not actually perform. Mirrors the Telegram/WhatsApp transports.
        """
        if not isinstance(
            message, OutboundSlackMessage
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "SlackTransport.post_message requires an OutboundSlackMessage; got "
                f"{type(message).__name__}"
            )
        logger.info(
            "slack.web.post_message.start",
            extra={"channel": message.channel, "base_url": self._config.base_url},
        )
        response = await self._client.chat_postMessage(
            channel=message.channel, text=message.text
        )
        data = _coerce_response(response)
        ok = bool(data.get("ok", False))
        ts = str(data.get("ts", ""))
        channel = str(data.get("channel", message.channel))
        if not ok:
            # API-level rejection at HTTP 200 — abort before the connector signs.
            error_code = str(data.get("error", "unknown"))
            logger.warning(
                "slack.web.post_message.rejected",
                extra={"channel": channel, "error": error_code},
            )
            raise SlackTransportError(f"Slack chat.postMessage rejected: {error_code}")
        if not ts:
            # ok:true but no message timestamp — no addressable message landed.
            logger.warning(
                "slack.web.post_message.missing_ts",
                extra={"channel": channel},
            )
            raise SlackTransportError(
                "Slack chat.postMessage returned ok:true with an empty 'ts'; "
                "no addressable message id to attest"
            )
        logger.info(
            "slack.web.post_message.ok",
            extra={"channel": channel, "ok": ok, "ts": ts},
        )
        return PostResult(ok=ok, ts=ts, channel=channel)

    async def history(
        self, channel: str, *, limit: int = 100
    ) -> list[InboundSlackMessage]:
        """Pull ONE bounded page of ``conversations.history`` for ``channel``.

        ``limit`` caps the page size (default 100, Slack's documented per-page
        cap). v0 does NOT cursor-paginate (ADR-S1): one page per call so the
        bounded shape matches the connector's single-audit-receipt-per-read
        contract. Returns the parsed list of :class:`InboundSlackMessage` (may
        be empty). The channel id is shape-validated at the boundary so a
        malformed channel never reaches the SDK call.
        """
        if (
            not isinstance(limit, int) or limit <= 0
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError(
                f"SlackTransport.history limit MUST be a positive int; got {limit!r}"
            )
        normalized_channel = normalize_slack_id(channel)
        logger.info(
            "slack.web.history.start",
            extra={
                "channel": normalized_channel,
                "limit": limit,
                "base_url": self._config.base_url,
            },
        )
        response = await self._client.conversations_history(
            channel=normalized_channel, limit=limit
        )
        data = _coerce_response(response)
        raw_messages = data.get("messages") or []
        messages: list[InboundSlackMessage] = []
        for raw in raw_messages:
            if not isinstance(raw, dict):
                # Slack only documents dict messages; skip non-dict entries
                # defensively rather than raising — keeps the read path
                # tolerant of historical API shape drift.
                continue
            messages.append(
                InboundSlackMessage(
                    channel=normalized_channel,
                    ts=str(raw.get("ts", "")),
                    user=str(raw.get("user", "")),
                    text=str(raw.get("text", "")),
                )
            )
        logger.info(
            "slack.web.history.ok",
            extra={"channel": normalized_channel, "count": len(messages)},
        )
        return messages


def _coerce_response(response: Any) -> dict[str, Any]:
    """Coerce an ``AsyncWebClient`` response to a plain ``dict``.

    The shipped ``AsyncWebClient`` returns a ``SlackResponse`` that supports
    ``__getitem__`` and ``.data`` (a dict). Tests may inject a plain dict.
    This helper accepts both shapes without importing ``SlackResponse`` (which
    would drag ``aiohttp`` into the Tier-1 import path).
    """
    # SlackResponse exposes the parsed body via ``.data``; prefer it when present.
    data = getattr(response, "data", response)
    if isinstance(data, dict):
        return data
    # Fallback: indexable shapes (very old SDK versions) — extract via ``dict()``.
    try:
        return dict(data)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            "Slack Web API response MUST be coercible to a dict; got "
            f"{type(response).__name__}"
        ) from exc
