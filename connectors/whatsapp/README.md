<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# delegate-connector-whatsapp

An OSS Python connector for the Terrene Delegate substrate. Implements the
shipped `kailash.delegate.Connector` ABC (kailash 2.26.2) for WhatsApp over the
first-party Meta Cloud API:

- **`write`** — Cloud API outbound send (`httpx POST /messages`), executed under
  audit, returns a real `SignedActionEnvelope`. Every send passes the
  template / service-window pre-flight gate (below).
- **`read`** — drains verified inbound messages from the webhook ingest buffer,
  executed under audit, returns `(messages, AttestedReadReceipt)`. Inbound is
  webhook-only: the connector ships the ingest protocol + buffer, NOT a running
  HTTP server (owning the public TLS socket is a deploy concern, not a
  connector-contract concern — WA-ADR-2).
- **`authenticate`** — resolves an E.164 sender to a `Principal` against the
  `PrincipalDirectory` (exact-match in v0; unknown sender → fail-closed
  `Reject` via `ConnectorAuthenticationError`).
- **`invoke`** — single-method dispatch entry (used by the dispatch hot path);
  dispatches a send and returns a `ConnectorInvocationResult`.
- Trust properties — `auth_verifier` returns the wired `Ed25519Verifier`;
  `ledger` / `revocation` return shipped concretes (framework-first; no custom
  trust primitives).

It subclasses `Connector` **directly** (mirroring email ADR-1) — NOT
`LegacyInvokeConnector`, whose proxied `read`/`write` emit empty, unverifiable
receipts. This connector's `read`/`write` produce non-empty receipts that verify
under a real `Ed25519Verifier`.

## Security properties

- **PII redaction** — the raw E.164 recipient never enters a log, audit-bytes
  payload, or ledger record. Persisted identity is a stable salted
  HMAC-SHA256 token (`wa:<hex>`); a redaction failure surfaces the
  `<unredactable wa identity>` sentinel, never the raw number. The
  `WHATSAPP_PII_HMAC_KEY` startup gate (`RedactionConfig.from_env`) makes an
  installation missing the key **refuse to start** — loud, not fail-soft.
- **Webhook HMAC boundary** — inbound `X-Hub-Signature-256` is verified
  constant-time; a tampered signature is refused and never reaches the buffer
  or the audit path. The `hub.verify_token` handshake echoes `hub.challenge`
  only on an exact token match.
- **Outbound gating** — free-form sends to a recipient outside the open 24h
  customer-service window raise a typed `OutsideServiceWindowError`; un-approved
  template names raise `TemplateNotApprovedError`. Both are pre-flight
  `Reject`s — NOT silent send failures — and fire NO Cloud API call. Approved
  templates are window-exempt (WA-ADR-4). The window tracker is bounded
  (LRU, default 100 000 entries) so the verified-inbound map cannot grow
  without limit.
- **Receipt identity-binding** — receipts sign over the FULL identity (signer +
  action/observed timestamps + content), not the bare payload; tampering ANY
  bound field fails `verify_action_envelope` / `verify_read_receipt`.

## Commercial-gateway disposition (stated openly)

Apache-2.0, Foundation-owned. The network endpoint is unavoidably commercial
(Meta Cloud API) — the same shape as the email connector's commercial SMTP host.
The shipped code path couples to **no intermediary vendor SDK**: the transport is
a generic `httpx` client against Meta's first-party Graph API, and the endpoint
URL is config, not code (WA-ADR-1, journal 0002). There is no dependency on any
proprietary sibling.

## Install

```bash
pip install -e connectors/whatsapp
```

## Configure

All credentials come from the environment (see `.env.example`); nothing is
hardcoded, nothing is logged. `.env` is git-ignored — only `.env.example` is
committed. The seven keys:

| Key                             | Purpose                                               |
| ------------------------------- | ----------------------------------------------------- |
| `WHATSAPP_ACCESS_TOKEN`         | Cloud API bearer token (Graph API auth)               |
| `WHATSAPP_PHONE_NUMBER_ID`      | the sending phone-number id (Cloud API path)          |
| `WHATSAPP_GRAPH_VERSION`        | Graph API version segment (e.g. `v21.0`)              |
| `WHATSAPP_APP_SECRET`           | HMAC key for `X-Hub-Signature-256` webhook verify     |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | the `hub.verify_token` handshake secret               |
| `WHATSAPP_PII_HMAC_KEY`         | salt for the `wa:`-token PII redactor (startup-gated) |
| `WHATSAPP_APPROVED_TEMPLATES`   | comma-separated approved-template allowlist           |

## Test

Tier-1 (unit, no I/O, no third-party transport lib required):

```bash
pip install -e "connectors/whatsapp[test]"
PYTHONPATH=connectors/whatsapp/src python -m pytest connectors/whatsapp/tests/unit -q
```

Tier-2 (in-process protocol-faithful Cloud API double — no mocks at the
boundary, no Docker, no vendor SDK):

```bash
PYTHONPATH=connectors/whatsapp/src python -m pytest connectors/whatsapp/tests/integration -q
```

The Tier-2 double is an `httpx.MockTransport`-backed deterministic adapter that
speaks the Meta `POST /messages` request/response shape — a Protocol-satisfying
surrogate, NOT a mock of the connector or the Cloud API client. Tier-3 is a
single opt-in `test_live_meta_sandbox` that runs against the real Meta sandbox
only when live `WHATSAPP_*` credentials are present; absent them it skips with a
"cannot execute" reason (never a mock fallback).

Conformance (shared canonical vector set) and the permanent security regression
suite:

```bash
PYTHONPATH=connectors/whatsapp/src python -m pytest \
  connectors/whatsapp/tests/conformance connectors/whatsapp/tests/regression -q
```

## Runtime execution — end-to-end

`compose.py` builds a real `DelegateRuntime` (over a `DispatchSurface`) around
the connector via `build_whatsapp_runtime`, driven with `await runtime.execute(...)`
(the dispatch entry is async — journal 0001). On `kailash >= 2.28.0` this runs
the full signed dispatch end-to-end: a COMPLETED run whose audit chain verifies
under a real `Ed25519Verifier`. The end-to-end `runtime.execute()` assertion is
exercised across the unit / integration / conformance suites, alongside the
connector's own `read`/`write` receipt verification.

> Historical note: earlier drafts (kailash `< 2.28.0`) hit an SDK audit-emit
> signature mismatch (kailash-py#1182) that failed `runtime.execute()` at the
> first audit emission. That is fixed; the connector floor is `kailash >= 2.28.0`.

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
