# Todo 07 — Tier-1 unit suite

**Implements:** `specs/test-infrastructure.md` § Tier 1 (+ `02-plans/02-connector-spec.md` § Security)
**Type:** Test · **Capacity:** single shard (boilerplate-heavy — one pattern per test)
**Depends:** 02–06

## Do

- `connectors/slack/tests/unit/` — pure-Python, no I/O. The external thunk is
  stubbed at the SDK boundary ONLY (the thunk itself, not the `Connector`/runtime
  contract). Cover:
  - Web API transport (todo 02): config-from-env errors on absent token; honors
    `SLACK_API_BASE_URL`; call-shape for `post_message` / `history`.
  - Injection boundary (todo 03): malformed channel id → `SlackFieldError`; mrkdwn
    escape of `&`/`<`/`>`; case-significant `normalize_slack_id`; frozen
    `OutboundSlackMessage`.
  - Principal resolution (todo 04): known `delegate_id` → `Principal`; unknown →
    `Reject`; secondary `by_slack_id` index; workspace id in `claims`.
  - Connector (todo 05): ABC `isinstance`; read/write return NON-empty verifiable
    receipts; trust properties return concretes.
  - **Receipt-binding REGRESSION tests** (value-anchor: brief "tamper of any field
    fails verification"): full-identity binding (two identical posts → different
    signed bytes); tamper of `signer` / `action_id` / `observed_at` each fails
    verification under the real verifier. Place behavioral (call the verifier,
    assert raise/return) — not source-grep.
  - **Authenticate-first REGRESSION test**: unknown sender on `invoke` raises
    BEFORE the post thunk runs (assert the thunk was never invoked).
  - Composition (todo 06): `build_slack_runtime` composes; `await
runtime.execute(...)` returns a result with a signed envelope (thunk stubbed).

## Acceptance

- [ ] `../../.venv/bin/pytest connectors/slack/tests/unit -q` green.
- [ ] No mocks of the `Connector`/runtime contract itself (only the external thunk
      boundary is stubbed at Tier-1).
- [ ] The unknown-sender `Reject` path AND each identity-field tamper path are
      covered explicitly (verified behaviorally, not by source-grep).
