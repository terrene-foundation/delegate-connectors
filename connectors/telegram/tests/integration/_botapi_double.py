# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""In-process, protocol-faithful Telegram Bot API double for the Tier-2 tier.

There is no local Telegram server (unlike email's Mailpit). The Tier-2
surrogate is an in-process ``httpx``-compatible responder built on
:class:`httpx.MockTransport` that speaks the Bot API ``POST .../sendMessage``
and ``GET .../getUpdates`` request/response shapes. This is a
**Protocol-satisfying deterministic adapter** (``rules/testing.md`` §
"Protocol Adapters" + T-ADR-1..T-ADR-5), NOT a mock:

- It is wired into a REAL :class:`httpx.AsyncClient`; the connector's REAL
  :class:`~delegate_connectors.telegram.transport.TelegramTransport` runs
  unmodified — the same ``_post_json`` / ``_get_json`` code paths, the same
  ``_raise_for_status`` envelope parsing, the same ``{base}/bot<token>/<method>``
  URL construction.
- It NEVER stubs ``TelegramTransport`` itself, never patches the ``Connector``
  contract, never substitutes a fake ``send`` / ``get_updates``. It only
  terminates the HTTP byte stream the production transport already emits.
- It records the exact request the production code sent (method, URL, JSON
  body for ``sendMessage``) so a test can assert the request matches the Bot
  API ``sendMessage`` contract — the request the live Bot API would receive.

The ``sendMessage`` response body mirrors the Bot API's documented success
envelope::

    {
      "ok": true,
      "result": {
        "message_id": <deterministic int>,
        "chat": {"id": <chat_id>},
        "text": <text>,
        "date": <fixed>
      }
    }

``getUpdates`` replays every recorded send as an ``Update``::

    {
      "ok": true,
      "result": [{"update_id": N, "message": {... echoing the send ...}}]
    }

The double is deterministic: the ``message_id`` is a content hash of the send
body, so two identical sends produce identical ``message_id`` values and the
two-runs-agree determinism contract holds at the transport boundary, not by
accident.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

_FIXED_DATE = 1700000000
_INBOUND_FROM_USER_ID = 424242


@dataclass(slots=True)
class RecordedRequest:
    """A single request the production transport sent to the double.

    Captured AFTER the production code built it, so assertions here are
    assertions about the bytes the live Telegram Bot API would have received.
    """

    method: str
    url: str
    json_body: dict[str, Any]
    method_name: str  # the Bot API method: "sendMessage" / "getUpdates"


@dataclass(slots=True)
class BotApiDouble:
    """A protocol-faithful, in-process Telegram Bot API responder.

    Build an :class:`httpx.AsyncClient` over :attr:`transport` and hand it to
    :class:`TelegramTransport(config, client=...)`. Every ``sendMessage`` /
    ``getUpdates`` the production transport emits is recorded on
    :attr:`requests`; ``sendMessage`` is answered with a Bot-API-shaped success
    envelope and the body is buffered on :attr:`delivered` so ``getUpdates`` can
    replay it.

    Set :attr:`force_status` to a non-2xx code (e.g. ``429``) to exercise the
    transport's typed-error path against a real ``httpx.Response`` — still no
    mock; the double simply returns the response the live API would on that
    failure mode. When ``force_status == 429`` and no ``force_body`` is set, the
    double returns the Bot API's ``parameters.retry_after`` envelope so the
    transport surfaces a :class:`RateLimitedError`.
    """

    requests: list[RecordedRequest] = field(default_factory=list)
    delivered: list[dict[str, Any]] = field(default_factory=list)
    force_status: int | None = None
    force_body: dict[str, Any] | None = None
    retry_after: int = 7

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> httpx.AsyncClient:
        """A real httpx.AsyncClient whose byte stream terminates at this double."""
        return httpx.AsyncClient(transport=self.transport)

    @property
    def last_request(self) -> RecordedRequest:
        if not self.requests:
            raise AssertionError("BotApiDouble received no requests")
        return self.requests[-1]

    @property
    def send_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.method_name == "sendMessage"]

    # ── handler ──────────────────────────────────────────────────────────

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method_name = request.url.path.rsplit("/", 1)[-1]
        body: dict[str, Any] = {}
        if request.content:
            try:
                parsed = json.loads(request.content.decode("utf-8"))
                if isinstance(parsed, dict):
                    body = parsed
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = {}
        self.requests.append(
            RecordedRequest(
                method=request.method,
                url=str(request.url),
                json_body=body,
                method_name=method_name,
            )
        )

        if self.force_status is not None:
            return self._forced_response()

        if method_name == "sendMessage":
            return self._handle_send(body)
        if method_name == "getUpdates":
            return self._handle_get_updates()
        # Unknown method — Bot API would 404; surface a non-ok envelope.
        return httpx.Response(404, json={"ok": False, "description": "Not Found"})

    def _forced_response(self) -> httpx.Response:
        if self.force_body is not None:
            return httpx.Response(self.force_status or 500, json=self.force_body)
        if self.force_status == 429:
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests: retry later",
                    "parameters": {"retry_after": self.retry_after},
                },
            )
        return httpx.Response(
            self.force_status or 500,
            json={"ok": False, "description": "forced error"},
        )

    def _handle_send(self, body: dict[str, Any]) -> httpx.Response:
        chat_id = body.get("chat_id")
        text = body.get("text", "")
        # Deterministic message_id: a content hash of the canonical send body so
        # two identical sends yield identical message_ids (the determinism
        # contract at the transport boundary).
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode("utf-8")
        ).hexdigest()
        message_id = int(digest[:8], 16)
        self.delivered.append(
            {"chat_id": chat_id, "text": text, "message_id": message_id}
        )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": message_id,
                    "chat": {"id": chat_id},
                    "text": text,
                    "date": _FIXED_DATE,
                },
            },
        )

    def _handle_get_updates(self) -> httpx.Response:
        result = []
        for offset, msg in enumerate(self.delivered, start=1):
            result.append(
                {
                    "update_id": offset,
                    "message": {
                        "message_id": msg["message_id"],
                        "chat": {"id": msg["chat_id"]},
                        "from": {"id": _INBOUND_FROM_USER_ID},
                        "text": msg["text"],
                        "date": _FIXED_DATE,
                    },
                }
            )
        return httpx.Response(200, json={"ok": True, "result": result})
