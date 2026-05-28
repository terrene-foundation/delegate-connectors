<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# delegate-connector-whatsapp

An OSS Python connector for the Terrene Delegate substrate, implementing the
shipped `kailash.delegate.Connector` ABC (kailash 2.26.2) for WhatsApp over the
first-party Meta Cloud API.

Apache-2.0, Foundation-owned. The network endpoint is unavoidably commercial
(Meta Cloud API) — the same shape as the email connector's commercial SMTP host
— but the shipped code path couples to NO intermediary vendor SDK. The transport
is a generic HTTP client against Meta's first-party Graph API; the endpoint URL
is config, not code (WA-ADR-1). There is no dependency on the proprietary Rust
sibling.

## Status (v0, Wave 1)

This package currently ships the pure-logic / stdlib-crypto security foundation:

- **PII redaction** — a stable salted-HMAC-SHA256 phone-number token
  (`wa:<8-hex>`); the raw E.164 never enters a log, audit payload, or ledger
  record.
- **Principal resolution** — `delegate_id`- and E.164-keyed; unknown sender →
  fail-closed `Reject`.
- **Webhook ingest protocol** — constant-time `X-Hub-Signature-256` HMAC verify
  - verify-token handshake + envelope parse into an in-process ingest buffer the
    `read` thunk drains. v0 ships the ingest protocol + buffer, NOT a running HTTP
    server (owning the public TLS socket is a deploy concern, not a
    connector-contract concern — WA-ADR-2).
- **Outbound gating** — pre-flight typed `Reject` for free-form sends outside the
  open 24h customer-service window (`OutsideServiceWindowError`) and for
  un-approved template names (`TemplateNotApprovedError`); approved-template
  sends are window-exempt (WA-ADR-4).

The Meta Cloud API outbound send (`httpx POST /messages`), the
`WhatsAppConnector` itself, runtime composition, and the full test/conformance
surface land in later waves.

## Configure

All credentials come from the environment (see `.env.example`):
`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_GRAPH_VERSION`,
`WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_PII_HMAC_KEY`,
`WHATSAPP_APPROVED_TEMPLATES`. Nothing is hardcoded; nothing is logged.

## Test

Tier-1 (unit, no I/O, no third-party transport lib required):

```bash
pip install -e "connectors/whatsapp[test]"
python -m pytest connectors/whatsapp/tests/unit -q
```

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
