<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# delegate-connector-email

The first OSS Python connector for the Terrene Delegate substrate. Implements the
shipped `kailash.delegate.Connector` ABC (kailash 2.26.2) for email:

- **`write`** — SMTP outbound send, executed under audit, returns a real
  `SignedActionEnvelope`.
- **`read`** — IMAP inbound fetch, executed under audit, returns
  `(messages, AttestedReadReceipt)`.
- **`authenticate`** — resolves a sender/recipient address to a `Principal`
  against a `PrincipalDirectory` (exact-match in v0; unknown sender → `Reject`,
  fail-closed).
- **`invoke`** — single-method dispatch entry (used by the dispatch hot path);
  dispatches a send and returns a `ConnectorInvocationResult`.
- Trust properties — `auth_verifier` returns the wired `Ed25519Verifier`;
  `ledger` / `revocation` return shipped concretes (framework-first; no custom
  trust primitives).

It subclasses `Connector` **directly** (ADR-1) — NOT `LegacyInvokeConnector`,
whose proxied `read`/`write` emit empty, unverifiable receipts. This connector's
`read`/`write` produce non-empty receipts that verify under a real
`Ed25519Verifier`.

## Install

```bash
pip install -e connectors/email
```

## Configure

All credentials come from the environment (see `.env.example`):
`EMAIL_SMTP_HOST/PORT/USER/PASSWORD/USE_TLS` and the `EMAIL_IMAP_*` equivalents.
Nothing is hardcoded; nothing is logged.

## Test

Tier-1 (unit, no I/O):

```bash
pip install -e "connectors/email[test]"
python -m pytest connectors/email/tests/unit -q
```

Tier-2/3 (real infra — Mailpit, no mocks at the boundary):

```bash
docker compose -f connectors/email/docker-compose.yml up -d
python -m pytest connectors/email/tests/integration -q
docker compose -f connectors/email/docker-compose.yml down
```

Mailpit exposes both SMTP (`:1025`) and IMAP (`:1143`) in one container, plus a
web UI at `:8025`. If Docker is unavailable the integration tests skip with a
clear reason (they do not fake the boundary).

## Known limitation — runtime `execute()` audit gate

`compose.py` builds a real `DelegateRuntime` around the connector. However the
shipped `kailash.delegate` runtime/dispatch audit-emit path signs the event
payload bytes while `AuditChainEngine.emit_event` verifies the signature against
the full audit-entry signing bytes — so `runtime.execute()` fails at the first
audit emission under any real verifier. This is an SDK bug in `kailash.delegate`,
not in this connector; the connector's own `read`/`write` receipts verify
correctly. See `workspaces/email/journal/0005-GAP-*` for the full evidence and
reproduction. The end-to-end `runtime.execute()` assertion is gated on the SDK
fix; the connector-level SMTP→IMAP round-trip and receipt verification are not.

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
