# CONVERGENCE — /redteam email connector

**Date:** 2026-05-27
**Phase:** /redteam
**Verdict:** CONVERGED — no remaining CRIT/HIGH.

## Durable receipts (per verify-resource-existence MUST-4)

**Gate reviews (round 1, parallel background agents):**

- reviewer (correctness): CLEAN — ABC fully satisfied (`__abstractmethods__ == frozenset()`,
  no empty-receipt proxy reliance), receipts verify under real `Ed25519Verifier` +
  reject foreign keys, unknown-sender fail-closed `Reject`, zero-tolerance clean,
  strict xfail + documented skip both correct, `--collect-only` exit 0.
- security-reviewer (round 1): 3 findings — H1 (HIGH) SMTP header injection (CRLF),
  M1 (MED) `invoke` sends without `authenticate`, L2 (LOW) receipt identity unbound.

**Hardening (round 1 fixes — all same-class, fixed immediately per autonomous-execution MUST-4):**

- H1 → commit `0dce4a0` (+ `frozenset` NEL/LS/PS follow-up): `validate_header_field` +
  `HeaderInjectionError` at the `OutboundMessage.__post_init__` chokepoint (frozen
  dataclass → no mutate-after-construct bypass; grep-confirmed single MIME site).
- M1 → commit `47005b6`: `invoke` calls `authenticate` first; unknown → `ConnectorAuthenticationError`, zero send.
- L2 → commit `b130c9c`: sign over `{payload/manifest, signer/attester_delegate_id, action_id/read_id, observed_at}`; tamper fails verify.
- Real IMAP → commit `0032369`: GreenMail (real SMTP+IMAP); inbound round-trip un-skipped, runs for real.

**Convergence re-review (round 2, security-reviewer):** CONVERGED — all 3 findings
genuinely CLOSED (bypass analysis incl. frozen-dataclass + U+2028/U+2029/NEL not a
vector through Python `BytesGenerator`); no new CRIT/HIGH; GreenMail `auth.disabled`
confirmed test-infra-only; no secrets logged.

**Test receipts:** full suite `52 passed, 2 xfailed, 0 skipped, 0 warnings` (re-run
independently against live Mailpit + GreenMail containers). The 2 xfailed are the
`runtime.execute()` e2e gated STRICT on the SDK audit-signature bug (journal 0005) —
flip to XPASS on the SDK fix, forcing the marker's removal.

## Scope NOT converged this cycle (by design)

- Conformance vectors — DEFERRED (journal 0003; cross-repo fixture sourcing gated on user authorization).
- `runtime.execute()` e2e — xfail gated on SDK bug (journal 0005; needs upstream kailash-py fix).

## Outstanding (non-blocking)

- SDK bug filing (journal 0005) — awaiting user yes/no (cross-repo action).
- PR merge of `feat/email-connector` — user's gate (L5: branch/commit/PR in-envelope, merge is user's).
