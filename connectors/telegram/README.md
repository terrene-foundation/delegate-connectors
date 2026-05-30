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

## Components

- **`transport.py`** — the `httpx`-backed Bot API transport (`sendMessage`
  outbound + `getUpdates` inbound long-poll). A Bot API `429` raises a typed
  `RateLimitedError` carrying `retry_after`; the caller decides backoff.
- **`connector.py`** — the `TelegramConnector` itself (the four ABC members + the
  three trust properties) plus the `verify_action_envelope` /
  `verify_read_receipt` helpers that re-derive identity-bound signing bytes.
- **`directory.py`** — the dual-keyed principal resolver + the closed-enum
  `UnknownSenderDisposition` (unknown sender → `Reject`).
- **`validation.py`** — pure message-content validation (control-character
  reject, `text` ≤ 4096 UTF-16 code units, `chat_id` shape), invoked at the
  `OutboundMessage` construction boundary so every send route is covered.
- **`compose.py`** — `build_telegram_runtime`, which composes a real
  `DelegateRuntime` around the connector with the shipped trust / audit /
  verifier concretes (no mocks).

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

```bash
pip install -e "connectors/telegram[test]"
# Tier 1 (unit)
python -m pytest connectors/telegram/tests/unit -q
# Tier 2/3 (integration — REAL TelegramTransport over a REAL httpx.AsyncClient
# whose byte stream terminates at an in-process protocol-faithful Bot API
# double; NO mock at the connector boundary, so these RUN in CI)
python -m pytest connectors/telegram/tests/integration -q
# Conformance (canonical conformance vector set)
python -m pytest connectors/telegram/tests/conformance -q
# Regression (behavioral security-property guards; NEVER deleted)
python -m pytest connectors/telegram/tests/regression -q
```

The opt-in Tier-3 live test (`test_live_telegram`) skips with a clear "cannot
execute" reason unless real `TELEGRAM_*` credentials are present — it never falls
back to a mock. The end-to-end `runtime.execute()` outcome assertions are
strict-`xfail` gated on an SDK fix (kailash-py#1182); the connector's own
read / write receipts verify today.

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
