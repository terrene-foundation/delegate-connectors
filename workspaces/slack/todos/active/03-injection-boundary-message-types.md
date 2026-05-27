# Todo 03 — Injection boundary + message types (`messages.py`)

**Implements:** `specs/connector-contract.md` § Type catalog (+ `02-plans/02-connector-spec.md` § Security, § Transport)
**Type:** Build (LOAD-BEARING) · **Capacity:** single shard (~250 LOC load-bearing, 5 invariants)
**Depends:** 01

## Do

- `src/delegate_connectors/slack/messages.py`:
  - `OutboundSlackMessage` (frozen dataclass) with `__post_init__` that (a)
    shape-validates every id-bound field (`channel`) via `normalize_slack_id`,
    and (b) mrkdwn-escapes user-controlled `text` (`&` → `&amp;`, `<` → `&lt;`,
    `>` → `&gt;`) per Slack's documented escaping contract, so an injected
    `<@U…>` mention / `<!channel>` broadcast / `<url|label>` link cannot render
    live. The construction boundary IS the validation boundary — every send route
    builds this first (ADR-S3).
  - `InboundSlackMessage` — normalized inbound shape (`channel`, `ts`, `user`,
    `text`) returned by the history pull.
  - `normalize_slack_id(value) -> str` — shape-validate + trim only; NOT lowercase
    (Slack ids are case-significant, a divergence from email's `normalize_address`).
  - `SlackFieldError` — typed error raised on a malformed id or invalid field.
  - Block Kit / `attachments` / `blocks` are OUT of v0 scope — do NOT add a
    structural-JSON surface (the structural-injection vector is removed by scoping
    them out, ADR-S3).

## Invariants (5)

1. `channel` (and any id-bound field) passes a Slack-id shape regex or raises
   `SlackFieldError`.
2. mrkdwn metacharacters `&`/`<`/`>` in `text` are escaped at construction.
3. Every outbound send route constructs an `OutboundSlackMessage` first (the single
   validation boundary).
4. `normalize_slack_id` is case-significant (does NOT lowercase).
5. No Block Kit / `attachments` structural-JSON surface in v0.

## Acceptance

- [ ] Unit: a malformed channel id raises `SlackFieldError`.
- [ ] Unit: `text` containing `<@U123>` / `<!channel>` / `&` is escaped so it
      cannot render as a live mention/broadcast/entity.
- [ ] Unit: a mixed-case Slack id round-trips unchanged (case preserved).
- [ ] Unit: constructing `OutboundSlackMessage` with valid inputs succeeds and is
      frozen (immutable).
