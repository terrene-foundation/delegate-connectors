# Todo 02 — Slack Web API transport (`web_api.py`)

**Implements:** `specs/test-infrastructure.md` § Tier 2/3 (real-boundary transport) (+ `02-plans/02-connector-spec.md` § Transport)
**Type:** Build · **Capacity:** single shard (~300 LOC, 4 invariants)
**Depends:** 01

## Do

- `src/delegate_connectors/slack/web_api.py`:
  - `SlackWebConfig.from_env()` — reads `SLACK_BOT_TOKEN` and optional
    `SLACK_API_BASE_URL` (the latter overrides the base URL so the Tier-2 mock
    container can stand in for the live Slack API). Absent token → typed error.
  - `SlackTransport` wrapping `slack_sdk.web.async_client.AsyncWebClient`:
    - `post_message(OutboundSlackMessage) -> PostResult` over `chat.postMessage`
      (outbound; returns the posted message `ts` + channel).
    - `history(channel, limit) -> list[InboundSlackMessage]` over
      `conversations.history` (bounded inbound pull — ADR-S1; one page, no
      cursor-pagination loop in v0).
  - Pure transport — NO audit logic here (the connector wraps these in audited
    thunks in todo 05).
- Credentials NEVER hardcoded; the one bot-token family covers both directions.

## Invariants (4)

1. Credentials read only from env; absent `SLACK_BOT_TOKEN` → typed config error,
   not a silent default.
2. No credential value appears in any log line.
3. `SLACK_API_BASE_URL` override actually retargets the `AsyncWebClient` base URL
   (the Tier-2 mock seam).
4. `history` returns a bounded page (`limit`-capped); no unbounded pagination loop.

## Acceptance

- [ ] Unit (Tier-1, no network): `SlackWebConfig.from_env()` errors clearly when
      `SLACK_BOT_TOKEN` is absent; honors `SLACK_API_BASE_URL` when present.
- [ ] Unit: `post_message` / `history` build the correct Web API call shape (thunk
      stubbed at the SDK boundary only).
- [ ] `grep` clean for hardcoded token/base-URL literals in `web_api.py`.
