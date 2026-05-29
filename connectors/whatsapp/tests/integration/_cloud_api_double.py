# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""In-process, protocol-faithful Meta Cloud API double for the Tier-2 tier.

There is no local WhatsApp server (unlike email's Mailpit). The Tier-2
surrogate is an in-process ``httpx``-compatible responder built on
:class:`httpx.MockTransport` that speaks the Meta Cloud API ``POST /messages``
request/response shape. This is a **Protocol-satisfying deterministic adapter**
(``rules/testing.md`` § "Protocol Adapters" + WA-ADR-1/WA-ADR-5), NOT a mock:

- It is wired into a REAL :class:`httpx.AsyncClient`; the connector's REAL
  :class:`~delegate_connectors.whatsapp.cloud_api.WhatsAppCloudApi` transport
  runs unmodified — the same ``_post_json`` code path, the same
  ``_raise_for_status`` envelope parsing, the same Bearer-header construction.
- It NEVER stubs ``WhatsAppCloudApi`` itself, never patches the ``Connector``
  contract, never substitutes a fake ``send``. It only terminates the HTTP
  byte stream the production transport already emits.
- It records the exact request the production code sent (method, URL, headers,
  JSON body) so a test can assert the request matches the Meta ``POST /messages``
  contract — the request the live Meta Graph API would have received.

The response body mirrors Meta's documented success envelope:

    {
      "messaging_product": "whatsapp",
      "contacts": [{"input": "<to>", "wa_id": "<to>"}],
      "messages": [{"id": "wamid.<base64-ish>"}]
    }

so ``messages[0].id`` is a ``wamid`` and ``contacts[0].wa_id`` is the resolved
recipient — exactly what :meth:`WhatsAppCloudApi.send` parses into a
:class:`~delegate_connectors.whatsapp.cloud_api.SendResult`.

The double is deterministic: a given ``to`` yields a stable ``wamid`` (a
content hash) so two identical runs produce byte-identical send envelopes —
the receipt-determinism invariant (todo invariant 4) holds at the transport
boundary, not by accident.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(slots=True)
class RecordedRequest:
    """A single request the production transport sent to the double.

    Captured AFTER the production code built it, so assertions here are
    assertions about the bytes the live Meta Graph API would have received.
    """

    method: str
    url: str
    headers: dict[str, str]
    json_body: dict[str, Any]


@dataclass(slots=True)
class CloudApiDouble:
    """A protocol-faithful, in-process Meta Cloud API responder.

    Build an :class:`httpx.AsyncClient` over :attr:`transport` and hand it to
    :class:`WhatsAppCloudApi(config, client=...)`. Every ``POST .../messages``
    the production transport emits is recorded on :attr:`requests` and answered
    with a Meta-shaped success envelope.

    Set :attr:`force_status` to a non-2xx code (e.g. ``429``) to exercise the
    transport's typed-error path against a real ``httpx.Response`` — still no
    mock; the double simply returns the response the live API would on that
    failure mode.
    """

    requests: list[RecordedRequest] = field(default_factory=list)
    force_status: int | None = None
    force_body: dict[str, Any] | None = None
    force_headers: dict[str, str] | None = None

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> httpx.AsyncClient:
        """A real httpx.AsyncClient whose byte stream terminates at this double."""
        return httpx.AsyncClient(transport=self.transport)

    @property
    def last_request(self) -> RecordedRequest:
        if not self.requests:
            raise AssertionError("CloudApiDouble received no requests")
        return self.requests[-1]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body_bytes = request.content
        try:
            parsed = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        self.requests.append(
            RecordedRequest(
                method=request.method,
                url=str(request.url),
                headers={k.lower(): v for k, v in request.headers.items()},
                json_body=parsed if isinstance(parsed, dict) else {},
            )
        )

        if self.force_status is not None:
            return httpx.Response(
                status_code=self.force_status,
                json=(
                    self.force_body
                    if self.force_body is not None
                    else {
                        "error": {
                            "message": "rate limited",
                            "error_data": {"details": "too many requests"},
                        }
                    }
                ),
                headers=self.force_headers or {},
            )

        # Meta-shaped success envelope. The wamid is a deterministic content
        # hash of the recipient so identical sends produce identical wamids —
        # which is what makes the two-runs-agree determinism contract hold at
        # the transport boundary.
        to = ""
        if isinstance(parsed, dict):
            to = str(parsed.get("to", ""))
        digest = hashlib.sha256(to.encode("utf-8")).digest()
        token = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:22]
        return httpx.Response(
            status_code=200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": to, "wa_id": to}],
                "messages": [{"id": f"wamid.{token}"}],
            },
        )
