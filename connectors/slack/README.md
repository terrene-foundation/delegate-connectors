<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# delegate-connector-slack

An OSS Python connector for the Terrene Delegate substrate. Implements the
shipped `kailash.delegate.Connector` ABC (kailash 2.26.2) for Slack — the same
contract the email + WhatsApp connectors implement, with a Slack Web API
transport:

- **`write`** — `chat.postMessage` outbound send via the Slack Web API
  (`AsyncWebClient`), executed under audit, returns a real
  `SignedActionEnvelope`.
- **`read`** — a bounded `conversations.history` pull (one page per call),
  executed under audit, returns `(messages, AttestedReadReceipt)`. The audited
  manifest carries the channel + message `ts` ids + count only — never message
  body bytes.
- **`authenticate`** — resolves a dispatch identity's `delegate_id` to a
  `Principal` against a `SlackPrincipalResolver` (exact-match in v0; an unknown
  identity resolves to `Reject`, fail-closed).
- **`invoke`** — single-method dispatch entry (used by the dispatch hot path);
  authenticates FIRST (so an unknown sender's `Reject` fires before any Slack
  API call), then posts via the audited `write` path and returns a
  `ConnectorInvocationResult`.
- Trust properties — `auth_verifier` returns the supplied real
  `Ed25519Verifier`; `ledger` returns an in-memory `InMemoryKnowledgeLedger`;
  `revocation` returns a never-revoked `NeverRevokedChannel` (both
  Protocol-satisfying deterministic concretes; framework-first, no custom trust
  primitives).

It subclasses `Connector` **directly** (ADR-1) — NOT `LegacyInvokeConnector`,
whose proxied `read`/`write` emit empty, unverifiable receipts. This connector's
`read`/`write` produce non-empty receipts that verify under a real
`Ed25519Verifier`. It has no Rust-sibling dependency — it is a pure-Python
connector.

## Inbound is a bounded `conversations.history` pull

Inbound messages are read via a bounded `conversations.history` pull, NOT Socket
Mode (ADR-S1). A persistent Socket Mode connection conflicts with the connector's
one-shot `read` thunk contract (one bounded fetch per audited read receipt), so
the connector pulls a single page per `read` call rather than holding an
event-streaming socket open.

## Injection boundary

User-controlled message text is mrkdwn-escaped (`&`/`<`/`>`) and every id-bound
field is shape-validated at the `OutboundSlackMessage` construction boundary
(ADR-S3), so an injected `<@U…>` mention, `<!channel>` broadcast, or
`<url|label>` link cannot render live. Every outbound send route builds an
`OutboundSlackMessage` first, so the boundary covers all of them. Block Kit /
`attachments` / `blocks` are out of v0 scope — scoping them out removes the
structural-injection vector entirely (ADR-S3).

## Install

```bash
pip install -e connectors/slack
```

## Configure

All credentials come from the environment (see `.env.example`):
`SLACK_BOT_TOKEN` is the `xoxb-…` bot token (required; one bot-token credential
family covers both directions). `SLACK_API_BASE_URL` optionally overrides the
Web API base URL — used to point the client at the local in-process test server.
Nothing is hardcoded; nothing is logged.

## Test

Tier-1 (unit, no I/O, no Slack Web API client required):

```bash
pip install -e "connectors/slack[test]"
python -m pytest connectors/slack/tests/unit -q
```

Tier-2/3 (real infra — an in-process protocol-faithful Slack Web API server over
a real socket; no mocks at the boundary):

```bash
python -m pytest connectors/slack/tests/integration -q
```

Because `slack_sdk`'s `AsyncWebClient` is aiohttp-based, the Tier-2 surrogate is
a **real in-process aiohttp server bound to an ephemeral port** (ADR-S4) — the
connector's real `AsyncWebClient` is pointed at it via `SLACK_API_BASE_URL`. This
is a Protocol-satisfying deterministic adapter over a real socket, not a mock at
the connector boundary, so the integration tests RUN (they do not skip). The
opt-in Tier-3 live-Slack test skips with a clear "cannot execute" reason unless
`SLACK_LIVE_E2E=1` plus real `SLACK_BOT_TOKEN` + `SLACK_LIVE_E2E_CHANNEL` are set
(it never falls back to a mock).

Conformance (canonical vector well-formedness + connector composition):

```bash
python -m pytest connectors/slack/tests/conformance -q
```

Regression (behavioral security guards — receipt identity binding,
authenticate-first fail-closed gate, outbound construction-boundary validation):

```bash
python -m pytest connectors/slack/tests/regression -q
```

## Runtime execution — end-to-end

`compose.py` builds a real `DelegateRuntime` around the connector, and
`runtime.execute(...)` runs the full signed dispatch end-to-end on
`kailash >= 2.28.0`: a COMPLETED run whose audit chain verifies under a real
`Ed25519Verifier`. The end-to-end `runtime.execute()` assertion is exercised in
the conformance + e2e suites; the connector-level post → history round-trip and
receipt verification are covered independently.

> Historical note: earlier drafts (kailash `< 2.28.0`) hit an SDK audit-emit
> signature mismatch (kailash-py#1182) that failed `runtime.execute()` at the
> first audit emission. That is fixed; the connector floor is `kailash >= 2.28.0`.

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
