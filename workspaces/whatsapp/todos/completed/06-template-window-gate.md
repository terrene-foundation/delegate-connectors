# Todo 06 — Template + service-window pre-flight Reject gate

**Implements:** `specs/connector-contract.md` § Methods (`invoke` gate) (+ `02-plans/02-connector-spec.md` § Outbound gating (template + service window))
**Type:** Build (LOAD-BEARING SECURITY) · **Capacity:** single shard (~200 LOC, 4 invariants)
**Depends:** 05

**Value-anchor:** delivers the brief acceptance criterion "Template-not-approved → typed `Reject` at the connector boundary, surfaced cleanly (NOT a silent send failure)" plus the spec's 24h-customer-service-window enforcement (WA-ADR-4).

## Do

- `src/delegate_connectors/whatsapp/templates.py`:
  - Approved-template allowlist seeded from `WHATSAPP_APPROVED_TEMPLATES` config.
  - Per-recipient 24h-window tracker — an in-memory last-inbound map fed by todo 05's
    buffer; reports whether a recipient's customer-service window is currently open.
  - `TemplateNotApprovedError` and `OutsideServiceWindowError` — both typed `Reject`s.
  - A pre-flight `check(payload) -> None | Reject` the connector (todo 07) calls BEFORE
    any Cloud API send. Meta's own error codes are mapped as a backstop only.

## Invariants (4)

1. The gate fires PRE-FLIGHT — before any side effect / Cloud API call.
2. A free-form (non-template) message to a recipient outside the open 24h window → `Reject`
   (`OutsideServiceWindowError`).
3. A send naming a template not in the allowlist → `Reject` (`TemplateNotApprovedError`).
4. An approved-template send is window-exempt (always allowed regardless of window state).

## Acceptance

- [ ] Unit (Tier-1): free-form to a recipient with no open window → `OutsideServiceWindowError`,
      and NO send was attempted (assert the transport was never called).
- [ ] Unit: un-approved template name → `TemplateNotApprovedError`, no send attempted.
- [ ] Unit: approved template → passes even with a closed window.
- [ ] Unit: free-form within an open window (recipient messaged < 24h ago) → passes.

## Verification

Completed in /implement Wave 1 (2026-05-28).

- `src/delegate_connectors/whatsapp/templates.py` created:
  `TemplateGate.check(recipient, *, template_name)` pre-flight gate raising
  typed `Reject`s; `OutsideServiceWindowError` + `TemplateNotApprovedError`
  (both subclass `WhatsAppRejectError`); `ServiceWindowTracker` (in-memory
  per-recipient last-inbound map fed by todo 05's `window_sink` via
  `record_inbound`, injectable clock for deterministic tests); allowlist seeded
  from `WHATSAPP_APPROVED_TEMPLATES` via `from_env_value`.
- Tier-1 tests `tests/unit/test_templates.py` — 12 tests, all green:
  - Free-form to a recipient with no open window → `OutsideServiceWindowError`,
    and the spy transport's `send` was never called (`calls == 0`).
  - Un-approved template name → `TemplateNotApprovedError`, no send attempted.
  - Approved template → passes even with a closed window (window-exempt).
  - Free-form within an open window (inbound < 24h ago) → passes.
  - Window closes after 24h (deterministic clock); unknown recipient is closed;
    absent/unparseable timestamps fall back to now without raising.
  - Window-tracker keys are symmetric with inbound normalization (a `+`-prefixed
    recipient resolves to a window opened under the bare-digit key).
- All 4 invariants hold: gate fires pre-flight before any side effect (1);
  free-form outside window → Reject (2); un-approved template → Reject (3);
  approved-template send window-exempt (4). The Cloud API POST itself is Wave 2
  (needs httpx) — the gate raises before any transport call, verified by the
  spy-transport `calls == 0` assertions.
