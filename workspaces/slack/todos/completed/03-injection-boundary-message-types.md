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

## Verification (Wave 1)

Implements `specs/connector-contract.md` § Type catalog + `02-plans/02-connector-spec.md` § Security, § Transport.

Created `src/delegate_connectors/slack/messages.py`:

- `OutboundSlackMessage` (frozen dataclass) — `__post_init__` shape-validates `channel` via `normalize_slack_id` and mrkdwn-escapes `text` (`&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;`, `&` escaped first), writing both back via `object.__setattr__` (the frozen-dataclass post-init pattern). The stored `text` is the already-escaped, send-safe value.
- `InboundSlackMessage` — normalized inbound shape (`channel`, `ts`, `user`, `text`); inbound text carried verbatim (escaping is an outbound concern).
- `normalize_slack_id(value) -> str` — shape-validate + trim only, case-significant (NOT lowercased); raises `SlackFieldError` on malformed input. Shape regex `^[A-Z][A-Z0-9]{7,}$` (open prefix, not a closed type allowlist) — matches the journal-0002 verified literals `U07ABCDE123` / `C0123456789`.
- `escape_mrkdwn(text)` — the standalone escape helper.
- `SlackFieldError` — typed error.
- No Block Kit / `attachments` / `blocks` structural-JSON surface (ADR-S3 — the structural-injection vector is removed by scoping it out).

Invariants satisfied:

1. `channel` passes the Slack-id shape regex or raises `SlackFieldError` (test: malformed channel raises).
2. `&`/`<`/`>` in `text` escaped at construction (tests: injected `<@U…>` mention, `<!channel>` broadcast, `<url|label>` link all rendered inert).
3. Every outbound send route constructs an `OutboundSlackMessage` first — the single validation boundary (Wave-1 there is no other send route; later transport/connector shards build this first per ADR-S3).
4. `normalize_slack_id` is case-significant — does NOT lowercase (test: valid uppercase id round-trips unchanged; lowercased variant is rejected as malformed).
5. No structural-JSON surface in v0 (no `blocks`/`attachments` field anywhere).

Design note surfaced + resolved during TDD: real Slack object ids are uppercase-only, so "case-significant" means "preserve the (uppercase) case, reject lowercased variants" — initial test fixtures used mixed-case ids that are genuinely malformed; fixtures corrected to demonstrate case-preservation via a valid uppercase id + a rejected lowercased variant.

Test result: covered by `connectors/slack/tests/unit/test_messages.py`. Full Wave-1 suite: **40 passed** (`PYTHONPATH=connectors/slack/src .venv/bin/python -m pytest connectors/slack/tests/unit -q`).
