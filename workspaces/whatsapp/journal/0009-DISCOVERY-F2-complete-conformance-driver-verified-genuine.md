# 0009 — DISCOVERY: F2 complete — all 16 #1182-gated markers removed; conformance driver adversarially verified genuine

**Type**: DISCOVERY
**Date**: 2026-05-31
**Phase**: /implement + /redteam (F2)
**Branch**: `feat/f2-runtime-e2e-unxfail` (12 commits, see `git log main..HEAD`)

## What shipped

F2 ("runtime e2e + conformance per-vector un-xfail, all 4 connectors") is
complete. All 16 kailash-py#1182-gated strict-xfail markers removed:

- **8 runtime-execute markers** (compose + e2e × 4 connectors) — replaced by real
  passing `runtime.execute()` end-to-end assertions (Classes B/C/D). This is the
  #1035 "Delegate runs end-to-end" value-anchor.
- **8 conformance markers** (per-vector + deterministic × 4) — replaced by a real
  per-vector driver materializing each canonical vector against the shipped
  kailash.delegate primitives (Class E). This is the `specs/conformance.md`
  checklist; STATUS flipped HALF-ACTIVE → ACTIVE.

Final state @ kailash 2.28.1 (`-W error::DeprecationWarning`): **440 passed,
3 skipped (Tier-3 live opt-in), 0 failures, 0 xfails, 0 warnings.**
slack 110 / telegram 122 / whatsapp 138 / email 70.

## Per-connector Class C harness fixes (the non-uniform-flip resolution from 0008)

- **slack**: clean flip (compose injects `_FakeAsyncWebClient`; e2e drives the socket double).
- **telegram**: e2e clean; compose made offline via an inline `httpx.MockTransport` bot-API double.
- **whatsapp**: `record_inbound` pre-warms the 24h service window so the freeform `{to,text}` send Accepts (template_name is not in the closed-world v0 input schema — Option B).
- **email**: added a `_send_fn` injection seam to `SmtpTransport` (mirrors slack's `_client=` seam) for the offline compose unit test; mailpit stood up locally so the `@requires_mailpit_smtp` e2e + determinism tests run for real.

Determinism `exclude_fields` corrected to the per-run-by-design set
`{run_id, at, dispatch_id, audit_head_hash, audit_chain_entries}` (+ `message_id`
for email, RFC-5322 per-message-unique) — not the single `audit_head_hash` that
0008 predicted (the 3-field reality was confirmed against a completing run).

## Conformance driver — adversarial verification (the receipts)

The per-vector driver (`connectors/*/tests/conformance/vector_driver.py`, copied
per-connector like `loader.py`) was scrutinized to rule out fake passes (a
passing conformance test that doesn't exercise its invariant is worse than an
xfail). Each vector raises/accepts for the RIGHT reason, with discrimination
controls (verified via direct primitive probes against kailash 2.28.1):

- **DV-3 (Reject)** — `cascade_child` with a child envelope widening the parent's
  Financial dim raises `EnvelopeWideningError` (the §3 monotonic-tightening gate).
- **DV-5 (Reject)** — `tighten_with(wider)` raises `EnvelopeWideningError`;
  **control**: `tighten_with(tighter)` SUCCEEDS → the test discriminates, not
  always-raise.
- **DV-7 (Reject)** — second `execute()` on a terminal runtime raises
  `RuntimePhaseError` ("single-shot per §7"), observed directly.
- **DV-9 (Accept)** — audit head-hash round-trip via `AuditChainEntry`
  to_canonical_dict→ctor→recompute reproduces the head EXACTLY; **control**: a
  tampered `previous_hash` makes the recomputed head differ → genuine,
  tamper-sensitive round-trip (not a tautology). (API deviation: there is no
  `AuditChain.from_dict`; the round-trip is via `AuditChainEntry.to_canonical_dict()`
  - constructor — verified byte-stable.)
- **DV-10 (Reject)** — binding a `principal_kind="sovereign"` identity to a
  `permitted_principal_kinds={"service_account"}` role raises
  `DispatchEnvelopeViolationError` with the exact `#1143 §10 G1 — service-account`
  message → the impersonation gate, not an incidental error.

API deviation note: DV-3's reject signal is `EnvelopeWideningError` (Financial
widening propagates through `cascade_child`), NOT `R2CompositionError` —
`R2Composition.validate` checks triplet object-identity, not envelope widening.
Both are in the driver's `_REJECT_ERRORS` set; the scrutiny confirmed the
SPECIFIC error fired for the SPECIFIC reason.

## Outstanding (post-F2)

- **F4** (first PyPI release) — user decided: cut after F2 lands on 2.28.x (now true). Needs human PyPI auth.
- **mailpit/greenmail containers** are running locally (`docker ps`) for email Tier-2; tear down with `docker compose -f connectors/email/docker-compose.yml down` when done. CI without mailpit SKIPs those tests (no failure).
- **F6** (wire-fidelity: schema-checked/replayed doubles, live Tier-3) — still open, TRACK ONLY (user-gated).
