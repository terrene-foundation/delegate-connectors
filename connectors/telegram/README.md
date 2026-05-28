<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# delegate-connector-telegram

An OSS Python connector for the Terrene Delegate substrate. Implements the
shipped `kailash.delegate.Connector` ABC (kailash 2.26.2) for Telegram via the
Bot API. It mirrors the email connector's shape and differs only in transport
(HTTP-only Bot API) and identity model (integer `user_id` / `chat_id`).

The connector contract (the shipped ABC — `authenticate / read / write / invoke`
plus the `auth_verifier / ledger / revocation` trust properties) is:

- **`write`** — `action` is a thunk wrapping a Bot API `sendMessage` POST,
  executed under audit, returning a real `SignedActionEnvelope`. The send is the
  auditable external side-effect.
- **`read`** — `query` is a thunk wrapping a Bot API `getUpdates` long-poll fetch,
  executed under audit, returning `(updates, AttestedReadReceipt)`.
- **`authenticate`** — resolves the dispatch identity's `delegate_id` to a
  `Principal` against a dual-keyed resolver (by stringified integer `user_id`
  and `chat_id`). An unknown identity resolves to `Reject` (fail-closed); a
  `@username` handle is never a resolution key (ref-unsafe and mutable).
- **`invoke`** — single-method dispatch entry: authenticate FIRST (fail-closed,
  before any Bot API call), then dispatch a send, returning a
  `ConnectorInvocationResult(external_side_effect=True)`.
- Trust properties — `auth_verifier` returns the wired `Ed25519Verifier`;
  `ledger` / `revocation` return shipped concretes (framework-first; no custom
  trust primitives).

It subclasses `Connector` **directly** (ADR-1) — NOT `LegacyInvokeConnector`,
whose proxied `read` / `write` emit empty, unverifiable receipts. There is no
stale `connect() / identify() / normalize()` surface; those methods do not exist
in the shipped ABC.

## Build status

This connector ships in waves. Landed today:

- **`directory.py`** — the dual-keyed principal resolver + the closed-enum
  `UnknownSenderDisposition` (unknown sender → `Reject`).
- **`validation.py`** — pure message-content validation (control-character
  reject, `text` ≤ 4096 UTF-16 code units, `chat_id` shape). No transport
  dependency; the `httpx`-backed `sendMessage` POST consumes these checks in a
  later wave.

The `httpx`-backed Bot API transport, the `TelegramConnector` itself, the
runtime composition, and the Tier-2/3 + conformance suites land in later waves.

## Install

```bash
pip install -e connectors/telegram
```

## Configure

All credentials come from the environment (see `.env.example`):
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_API_BASE`. Nothing is hardcoded; nothing is
logged. The token is part of the request URL, so the transport logs the method +
chat, never the URL.

## Test

Tier-1 (unit, no I/O, no third-party transport lib required):

```bash
pip install -e "connectors/telegram[test]"
python -m pytest connectors/telegram/tests/unit -q
```

Tier-2/3 (real infra — a local Bot API HTTP service, no mocks at the boundary)
land in a later wave; see `docker-compose.yml` for the service that will back
them. If Docker is unavailable those tests skip with a clear reason (they do not
fake the boundary).

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
