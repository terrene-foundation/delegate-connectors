<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# delegate-connector-slack

An OSS Python connector for the Terrene Delegate substrate. Implements the
shipped `kailash.delegate.Connector` ABC (kailash 2.26.2) for Slack — the same
contract the email connector implements, with a different transport.

> **Status: scaffold + pure-logic foundation (v0, in progress).** This package
> currently ships the message types + injection boundary (`messages.py`) and the
> principal resolver (`directory.py`). The Slack Web API transport, the
> `SlackConnector`, the runtime composition, and the test/conformance suites land
> in later shards. The full connector overview is filled in when those land.

## Design (v0)

- **`write`** — `chat.postMessage` outbound send via the Slack Web API
  (`AsyncWebClient`), executed under audit, returns a `SignedActionEnvelope`.
- **`read`** — a bounded `conversations.history` pull, executed under audit,
  returns `(messages, AttestedReadReceipt)`. Socket Mode is NOT used — a
  persistent socket conflicts with the one-shot `read` thunk (ADR-S1).
- **`authenticate`** — resolves a dispatch identity's `delegate_id` to a
  `Principal` against a `SlackPrincipalResolver` (exact-match in v0; an unknown
  identity resolves to `Reject`, fail-closed).
- One bot-token credential family (`SLACK_BOT_TOKEN`) covers both directions.

## Injection boundary

User-controlled message text is mrkdwn-escaped (`&`/`<`/`>`) and every id-bound
field is shape-validated at the `OutboundSlackMessage` construction boundary, so
an injected `<@U…>` mention, `<!channel>` broadcast, or `<url|label>` link cannot
render live. Every outbound send route builds an `OutboundSlackMessage` first, so
the boundary covers all of them. Block Kit / `attachments` / `blocks` are out of
v0 scope (the structural-injection vector is removed by scoping them out, ADR-S3).

## Configure

All credentials come from the environment (see `.env.example`):
`SLACK_BOT_TOKEN` is the bot token; `SLACK_API_BASE_URL` optionally overrides the
Web API base URL (used to point the client at the local mock-server container).
Nothing is hardcoded; nothing is logged.

## Test

Tier-1 (unit, no I/O, no Slack Web API client required):

```bash
pip install -e "connectors/slack[test]"
python -m pytest connectors/slack/tests/unit -q
```

Tier-2/3 (real Web API client against a local mock-server container) land in a
later shard.

## License

Apache 2.0. All open-source IP is owned by the Terrene Foundation.
