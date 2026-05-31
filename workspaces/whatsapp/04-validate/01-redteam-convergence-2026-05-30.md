# /redteam Convergence Receipt — delegate-connectors (4-connector trust surface)

**Date**: 2026-05-30
**Posture**: L5_DELEGATED (fresh repo)
**Branch**: `fix/connectors-trust-surface-redteam` (commits `451eab2..HEAD`)
**Verdict**: CONVERGED — 0 CRITICAL, 0 HIGH on the working tree (one HIGH is upstream-only; see below).

## Rounds

### Round 1 — discovery (3 parallel audits + 1 spec-author agent)

| Agent              | Role                                    | Task ID             |
| ------------------ | --------------------------------------- | ------------------- |
| analyst            | spec-compliance audit                   | `ac0e72f10239a2bd3` |
| testing-specialist | false-green / test-integrity sweep      | `a46442d2cc1f6b1f7` |
| security-reviewer  | trust-surface audit                     | `ac30a97e9494fd82c` |
| general-purpose    | author specs/whatsapp-connector.md (F1) | `a324abe5952cf1f9c` |

### Round 2 — independent re-verification (2 parallel agents over the full diff)

| Agent              | Role                                              | Task ID             | Verdict                                                  |
| ------------------ | ------------------------------------------------- | ------------------- | -------------------------------------------------------- |
| security-reviewer  | re-verify fixes + sweep for regressions           | `a515d348afad59f8f` | PASS — 0 new, 0 CRITICAL, 0 HIGH (excl. upstream HIGH-1) |
| testing-specialist | full suites + bug-class re-sweep + spec citations | `af8d6ef12f869bd9c` | PASS — all green; 1 LOW (spec line drift, now fixed)     |

Round-2 testing agent empirically proved the telegram signer-tamper fix: old form returned `True` for the wrong reason (empty-`observed_at` divergence); new form makes the attacker signer the sole source of byte divergence.

## Findings & dispositions

| ID            | Severity        | Finding                                                                                                                                                                                                                    | Disposition                                                          | Commit                 |
| ------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ---------------------- |
| CRIT-1        | CRITICAL        | Slack `post_message` returned `PostResult(ok=False)` on `{"ok":false}` (HTTP 200); connector signed a verifying envelope for a send Slack rejected — forged proof of an action that never happened (the F6 concern, live). | Fixed — raises `SlackTransportError` before signing.                 | `245e72b`              |
| F5            | CRITICAL (test) | whatsapp e2e `verify_action_envelope(..., observed_at=payload.get("observed_at",""))` always failed (observed_at not in payload) and `or verifier.verify(...)` masked it — the envelope-level check was dead.              | Fixed — recover observed_at from `canonical_bytes`; single assert.   | `436dee3`              |
| HIGH-2        | HIGH            | Email `SmtpTransport.send` returned `accepted=False` on total SMTP refusal; connector signed an envelope for an email delivered to nobody.                                                                                 | Fixed — raises `SmtpSendError` before signing.                       | `245e72b`              |
| (telegram)    | HIGH            | Signer-tamper regression test passed on the empty-`observed_at` mismatch, never reaching the signer-binding check.                                                                                                         | Fixed — pass real observed_at.                                       | `436dee3`              |
| F1            | HIGH            | WhatsApp (largest connector) shipped with no spec; slack/telegram specs cite it as sibling.                                                                                                                                | Fixed — `specs/whatsapp-connector.md` (grounded, cited) + index row. | `8a63047`              |
| MED-1         | MED             | Slack signed `ts:""` (no addressable message id).                                                                                                                                                                          | Fixed — raises on ok:true + empty ts.                                | `245e72b`              |
| MED-2         | MED             | whatsapp `WebhookIngest._buffer` unbounded list (memory-exhaustion DoS).                                                                                                                                                   | Fixed — `deque(maxlen=10_000)` + WARN-on-evict + `popleft`.          | `00653cd`              |
| F2/F3/F4      | MED/LOW         | index inconsistency; email authenticate spec said email-address (code = delegate_id); email conformance missing the receipts-agree xfail.                                                                                  | Fixed.                                                               | `8a63047`              |
| (coverage)    | MED             | telegram/whatsapp doubles' `force_status` failure path never exercised at Tier-2.                                                                                                                                          | Fixed — one reject-before-sign integration test per connector.       | `00653cd`              |
| (spec)        | LOW             | whatsapp spec webhook.py citations drifted after MED-2 line shift (same PR).                                                                                                                                               | Fixed — re-anchored to def-start lines.                              | `a0c9ef8`              |
| (deprecation) | LOW             | pytest-asyncio `asyncio_default_fixture_loop_scope` unset.                                                                                                                                                                 | Fixed — set "function" across all 4.                                 | (pytest-config commit) |

## Test posture (from-scratch run, `.venv/bin/python`, kailash 2.26.2)

| Connector | passed | skipped | xfailed | failed |
| --------- | ------ | ------- | ------- | ------ |
| email     | 59     | 4       | 7       | 0      |
| slack     | 102    | 1       | 8       | 0      |
| telegram  | 114    | 1       | 8       | 0      |
| whatsapp  | 130    | 1       | 8       | 0      |

`pytest --collect-only` exit 0 for all four (merge gate). Skips are live-gated Tier-3 (no creds) — SKIP, never mock-fallback. Xfails are the kailash-py#1182-gated strict-xfails (intact, not prematurely un-wired).

Mechanical sweeps (Round-2): no masked-`or` verify idioms; no payload-sourced observed_at; all 4 transports raise on API-level failure; all new public symbols (`SlackTransportError`, `SmtpSendError`, `max_buffered`) have exercising tests; every whatsapp-spec symbol citation resolves.

## Open items requiring user decision (NOT convergence-blocking)

- **HIGH-1 (upstream)**: `SignedActionEnvelope` (`kailash.delegate.dispatch`) has no `observed_at` field, so write-envelope time is committed inside `canonical_bytes` but not independently verifiable from the envelope object (unlike `AttestedReadReceipt.observed_at`). `verify_action_envelope` requires the caller to supply observed_at. Not fixable in this repo without an SDK change or a connector payload-contract change. Disposition options: (a) bind observed_at into local payload; (b) file upstream kailash issue (human-gated per upstream-issue-hygiene.md); (c) accept + document. Recommendation: surface to user.
- **kailash floor**: all 4 pyproject declare `kailash>=2.24.0` but the 4-primitive Connector ABC is verified only at 2.26.2. If the ABC landed after 2.24.0, the floor breaks 3rd-party installs (blocks the F4 PyPI release). Needs verification against the 2.24.0 wheel before first release.

## Deferred (value-anchored follow-ups; below convergence line)

- **LOW-1**: `_as_payload`/`_read_manifest` repr() fallback could serialize a non-dict into signed bytes. Value-anchor: trust-surface hygiene (#1035 OSS-usability) — dead on happy path today (thunks return dicts); becomes live only if a future transport returns a non-dict. Re-validate before any transport refactor.
- **Hygiene (from F1 spec read)**: (a) `compose.py:253` `object.__setattr__` private-field mutation to wire window_sink — API hygiene; (b) `_require_env` triplicated across cloud_api/webhook/redaction — the redaction.py comment's "consolidate when third surface lands" trigger has been met. Value-anchor: maintainability of the OSS connector set (#1035).
