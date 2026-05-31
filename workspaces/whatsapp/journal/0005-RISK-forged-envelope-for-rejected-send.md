# 0005 — RISK: forged signed envelope for an API-rejected send

**Type**: RISK
**Date**: 2026-05-30
**Surfaced by**: /redteam (security-reviewer, Round 1, task `ac30a97e9494fd82c`)
**Status**: RESOLVED (commit `245e72b`); re-verified Round 2 (task `a515d348afad59f8f`)

## The risk

The connectors' core promise is: **a signed `SignedActionEnvelope` verifies only
for an action that actually occurred and was performed by the bound delegate
identity.** Two of the four connectors violated it at the transport→sign seam.

- **Slack (CRITICAL)**: `chat.postMessage` returns `{"ok": false, "error": ...}`
  at **HTTP 200** when a post is rejected (`channel_not_found`, `not_in_channel`,
  `is_archived`, ...). `SlackTransport.post_message` propagated this as
  `PostResult(ok=False)` **without raising**. The connector's `write` path signs
  whatever the thunk returns, so it produced a fully-verifying envelope + ledger
  row + `external_side_effect=True` for a message that was **never delivered**.
  A legitimate-but-curious operator could obtain cryptographic "proof" of a send
  that the API rejected.

- **Email (HIGH)**: same class. `aiosmtplib.send` returns a non-empty `errors`
  map (not a raise) on a total per-recipient refusal (`550`); the transport
  signed `accepted=False`.

Telegram and WhatsApp already raised on non-ok envelopes — the asymmetry was the
tell.

## Why it mattered

The "negative outcome recorded in a signed payload" framing (Slack transport
docstring) is a false comfort: the audit chain does **not** distinguish a signed
success from a signed failure — both verify identically. A `False` buried inside
signed bytes is not a negative-outcome record; it is a forged positive proof.

This is the **F6 wire-fidelity / trust-surface concern** the user approved
tracking — surfaced here as a **live CRITICAL**, not a future hardening item.

## Resolution

Both transports now **raise before returning** on API-level rejection
(`SlackTransportError` / `SmtpSendError`), so the raise propagates out of `write`
**before** any signing primitive (`build_*_signing_bytes` / `_sign` /
`ledger.record`). Verified structurally: `write` does `await action()` first;
the raise aborts the path before signing. Slack also raises on `ok:true` with an
empty `ts` (no addressable message id to attest). Connector-level reject-before-
sign is now covered by a Tier-2 test per connector (force a 429 → `write` raises
→ no envelope). All four transports now fail-closed on negative external
outcomes.

## Residual

**HIGH-1 (upstream)**: write-envelope `observed_at` is committed inside
`canonical_bytes` but is not a first-class field on `SignedActionEnvelope`
(`kailash.delegate.dispatch`), so it is not independently verifiable from the
envelope object the way `AttestedReadReceipt.observed_at` is. Not fixable in this
repo without an SDK change. Surfaced to the user for disposition.
