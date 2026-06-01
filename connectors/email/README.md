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

Tier-2/3 (real infra — Mailpit + GreenMail, no mocks at the boundary):

```bash
docker compose -f connectors/email/docker-compose.yml up -d
python -m pytest connectors/email/tests/integration -q
docker compose -f connectors/email/docker-compose.yml down
```

Two real mail servers back the tier: **Mailpit** (SMTP `:1025` + REST/UI `:8025`)
for the outbound send + arrival assertion, and **GreenMail** (`greenmail/standalone`;
real SMTP `:3025` + real IMAP `:3143`) for the inbound IMAP round-trip — Mailpit
v1.30.0 ships no IMAP server. If Docker is unavailable the integration tests skip
with a clear reason (they do not fake the boundary).

## Runtime execution — end-to-end

`compose.py` builds a real `DelegateRuntime` around the connector
(`build_email_runtime`), and `runtime.execute(...)` runs the full signed
dispatch end-to-end on `kailash >= 2.28.0`: a COMPLETED run whose audit chain
verifies under a real `Ed25519Verifier`. The end-to-end `runtime.execute()`
assertion is exercised in the integration + conformance suites (it skips, never
fakes, when the Mailpit/GreenMail backends are unavailable).

> Historical note: earlier drafts (kailash `< 2.28.0`) hit an SDK audit-emit
> signature mismatch (kailash-py#1182) that failed `runtime.execute()` at the
> first audit emission. That is fixed; the connector floor is `kailash >= 2.28.0`.

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
