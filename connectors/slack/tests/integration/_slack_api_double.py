# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""In-process, protocol-faithful Slack Web API double for the Tier-2 tier.

Slack's ``slack_sdk.web.async_client.AsyncWebClient`` is **aiohttp**-based, so the
WhatsApp approach (``httpx.MockTransport``) cannot intercept it. Instead this
module stands up a **real in-process aiohttp server on an ephemeral port**
(port 0) and the connector's REAL ``AsyncWebClient`` is pointed at
``http://127.0.0.1:<port>/`` via the ``SLACK_API_BASE_URL`` override (ADR-S4).

This is a **Protocol-satisfying deterministic adapter over a REAL socket**
(``rules/testing.md`` § "Protocol Adapters" + ADR-S4), NOT a mock at the connector
boundary:

- It is served to a REAL :class:`~slack_sdk.web.async_client.AsyncWebClient`; the
  connector's REAL :class:`~delegate_connectors.slack.web_api.SlackTransport` runs
  unmodified — the same ``chat_postMessage`` / ``conversations_history`` code
  path, the same Bearer-header construction, the same ``_coerce_response``
  parsing.
- It NEVER stubs ``SlackTransport`` itself, never patches the ``Connector``
  contract, never substitutes a fake ``post_message`` / ``history``. It only
  terminates the HTTP byte stream the production transport already emits.
- It records the exact request the production code sent (method, channel, text,
  auth header) so a test can assert the request matches the Slack Web API
  contract — the request the live Slack API would have received.

The two methods v0 uses:

- ``POST /chat.postMessage`` — records the post (channel, text, auth header) and
  returns a Slack-shaped success envelope. The ``ts`` is a DETERMINISTIC content
  hash of ``channel + text`` so two identical posts produce identical envelopes
  (the receipt-determinism invariant holds at the transport boundary, not by
  accident).
- ``POST|GET /conversations.history`` — replays the recorded posts for the
  requested channel as ``{"ok": true, "messages": [...]}``.

The server is started on port 0 via ``aiohttp.web.AppRunner`` + ``TCPSite``; the
bound ``base_url`` (``http://127.0.0.1:<port>/``) is exposed for the connector
config. The runner + site are closed in ``stop()`` so the fixture's teardown
leaves no unclosed sockets (``rules/testing.md`` resource-cleanup).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from aiohttp import web

#: Shared deterministic test constants. Imported by name by the integration +
#: regression conftests AND the test modules, so test modules never need to
#: ``from conftest import ...`` (which collides across tier directories under
#: pytest's rootdir-import mode).
SENDER_SLACK_ID = "U07ABCDE123"
CHANNEL_ID = "C0123456789"
TEST_BOT_TOKEN = "xoxb-test-not-a-real-bot-token"


@dataclass(slots=True)
class RecordedPost:
    """A single ``chat.postMessage`` the production transport sent to the double.

    Captured AFTER the production code built it, so assertions here are assertions
    about the bytes the live Slack API would have received.
    """

    channel: str
    text: str
    authorization: str
    ts: str


def _deterministic_ts(channel: str, text: str) -> str:
    """A stable Slack-shaped ``ts`` derived from the message content.

    Identical (channel, text) → identical ts, so two identical posts produce
    byte-identical signed envelopes (receipt-determinism invariant). The shape
    mirrors Slack's ``<seconds>.<microseconds>`` timestamp id.
    """
    digest = hashlib.sha256(f"{channel}\x00{text}".encode("utf-8")).hexdigest()
    seconds = int(digest[:8], 16) % 10_000_000_000
    micros = int(digest[8:14], 16) % 1_000_000
    return f"{seconds:010d}.{micros:06d}"


class SlackApiDouble:
    """A protocol-faithful, in-process Slack Web API responder over a real socket.

    Start with :meth:`start` (binds an ephemeral port); read :attr:`base_url` and
    hand it to ``SlackWebConfig(base_url=...)`` so the connector's REAL
    ``AsyncWebClient`` posts to this server. :attr:`posts` records every
    ``chat.postMessage`` the production transport emits; the history endpoint
    replays them.
    """

    def __init__(self) -> None:
        self.posts: list[RecordedPost] = []
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._base_url: str | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> "SlackApiDouble":
        app = web.Application()
        app.router.add_post("/chat.postMessage", self._handle_post_message)
        # AsyncWebClient issues POST for Web API methods; accept GET too so the
        # history surface is callable either way (defensive, protocol-faithful).
        app.router.add_post("/conversations.history", self._handle_history)
        app.router.add_get("/conversations.history", self._handle_history)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host="127.0.0.1", port=0)
        await self._site.start()

        # Resolve the OS-assigned ephemeral port from the bound server socket.
        server = self._site._server  # type: ignore[attr-defined]
        sockets = getattr(server, "sockets", None) or []
        port = sockets[0].getsockname()[1]
        # Trailing slash matches AsyncWebClient's base_url join contract
        # (base_url + api_method).
        self._base_url = f"http://127.0.0.1:{port}/"
        return self

    async def stop(self) -> None:
        # Close site then runner so no aiohttp connector / socket is left open at
        # fixture teardown.
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def __aenter__(self) -> "SlackApiDouble":
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # ── inspection surface ───────────────────────────────────────────────

    @property
    def base_url(self) -> str:
        if self._base_url is None:
            raise AssertionError("SlackApiDouble.start() not called")
        return self._base_url

    @property
    def last_post(self) -> RecordedPost:
        if not self.posts:
            raise AssertionError("SlackApiDouble received no chat.postMessage requests")
        return self.posts[-1]

    def history_for(self, channel: str) -> list[dict[str, Any]]:
        """The recorded posts for ``channel`` in Slack ``messages`` shape.

        Exposes the double's OWN view of stored messages — a test asserts through
        THIS surface (not connector internal state) that a post landed.
        """
        return [
            {"ts": p.ts, "user": "", "text": p.text}
            for p in self.posts
            if p.channel == channel
        ]

    # ── handlers ─────────────────────────────────────────────────────────

    async def _read_params(self, request: web.Request) -> dict[str, str]:
        """Parse channel/text from whichever body shape the SDK used.

        AsyncWebClient sends Web API params as form-encoded POST data by default;
        tolerate JSON and query-string too so the double is robust to SDK shape
        drift.
        """
        params: dict[str, str] = dict(request.query)
        if request.can_read_body:
            ctype = request.headers.get("Content-Type", "")
            if "application/json" in ctype:
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        params.update({k: str(v) for k, v in body.items()})
                except Exception:  # pragma: no cover - defensive
                    pass
            else:
                form = await request.post()
                params.update({k: str(v) for k, v in form.items()})
        return params

    async def _handle_post_message(self, request: web.Request) -> web.Response:
        params = await self._read_params(request)
        channel = params.get("channel", "")
        text = params.get("text", "")
        authorization = request.headers.get("Authorization", "")
        ts = _deterministic_ts(channel, text)
        self.posts.append(
            RecordedPost(
                channel=channel,
                text=text,
                authorization=authorization,
                ts=ts,
            )
        )
        return web.json_response(
            {
                "ok": True,
                "channel": channel,
                "ts": ts,
                "message": {"text": text, "ts": ts, "type": "message"},
            }
        )

    async def _handle_history(self, request: web.Request) -> web.Response:
        params = await self._read_params(request)
        channel = params.get("channel", "")
        return web.json_response(
            {
                "ok": True,
                "messages": self.history_for(channel),
                "has_more": False,
            }
        )
