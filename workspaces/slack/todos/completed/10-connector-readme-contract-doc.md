# Todo 10 — Connector README + contract doc

**Implements:** `specs/monorepo-layout.md` § Package shape (README) + `specs/connector-contract.md` § Divergence (+ `02-plans/02-connector-spec.md` § Responsibilities, § Transport, § Security)
**Type:** Docs · **Capacity:** single shard (small, doc-only)
**Depends:** 05 (so the doc reflects the verified shape)

## Do

- Fill `connectors/slack/README.md` (scaffolded in todo 01) to describe the SHIPPED
  contract (mirror the email connector README shape):
  - the 4 ABC members + 3 trust properties as the slack connector implements them
    (`write` = `chat.postMessage` under audit → `SignedActionEnvelope`; `read` =
    bounded `conversations.history` pull under audit → `(messages,
AttestedReadReceipt)`; `authenticate` = `delegate_id` → `Principal`, unknown →
    fail-closed `Reject`; `invoke` = authenticate-first hot path → post);
  - subclasses `Connector` DIRECTLY (ADR-1) — NOT `LegacyInvokeConnector`;
  - inbound transport is the bounded `conversations.history` pull, NOT Socket Mode
    (ADR-S1) — name the structural reason so a future reader does not re-litigate it;
  - install + `.env` (`SLACK_BOT_TOKEN`, optional `SLACK_API_BASE_URL`); credentials
    env-only, nothing logged;
  - Apache-2.0; no dependency on the Rust sibling.
- Describe ONLY shipped behavior (per `rules/spec-accuracy.md`): no Socket Mode /
  OAuth / Block Kit "coming soon" framing — those are bounded out-of-scope, not gaps.
- The shared `specs/slack-connector.md` promotion from `02-plans/02-connector-spec.md`
  (+ a `specs/_index.md` row) lands when `/implement` puts the connector code on the
  default branch (per the spec's own status note + `rules/spec-accuracy.md` Rule 5) —
  flag it here so the promotion is not dropped.

## Acceptance

- [ ] `connectors/slack/README.md` connector section matches `specs/connector-contract.md` + the slack-specific ADRs (S1–S4).
- [ ] No "coming soon" / Socket-Mode-default / Block-Kit framing for unshipped behavior.
- [ ] Ships as a separate doc-only commit/PR (not bundled with connector code).
