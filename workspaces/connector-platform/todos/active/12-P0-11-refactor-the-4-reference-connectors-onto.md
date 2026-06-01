# P0-11 — Refactor the 4 reference connectors onto factory + broker + host-side signing + host-owned invocation (declare delegate_host_protocol + requires_credentials; remove os.environ; fold the P0-09 seam) — slack/email/telegram parallel, whatsapp dedicated pass

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** YES  ·  **Est:** ~340 LOC
> **Depends on:** P0-07, P0-09, P0-10a, P0-10b
> **Implements:** architecture §7 Phase 0; architecture § risks (references self-acquire credentials); specs CONNECTORS refactor_notes (per connector); rules/autonomous-execution.md § Per-Session Capacity Budget

## What (≤3 sentences)

Refactor each reference connector to compose via connector_builder() (P0-10a/b), receive BoundTransport handles from the broker (P0-07, no os.environ reads), declare requires_credentials + delegate_host_protocol, rely on host-side signing + host-owned side-effect invocation (folding the P0-09 seam directly into each worktree). Per capacity MEDIUM findings: slack first (cleanest baseline) to validate the pattern; then email + telegram in parallel; whatsapp runs as its OWN dedicated worktree pass (NOT one of a simultaneous fan-out) because it is materially denser (~7 simultaneous invariants: 4-secret/3-file os.environ sweep + 3 credential classes + window + template-gate + PII floor + factory-compose + protocol declaration).

## Deliverable

Four refactored reference connectors (email dual SMTP+IMAP, slack single, telegram single, whatsapp dual asymmetric + 4-secret broker + PII gate) composing via the factory + broker, with zero os.environ reads and zero credential-leaking .config accessors reachable from the connector, each folding its P0-09 seam.

## Files touched

- connectors/email/.../smtp.py:126,163-165 + imap.py:46,75-77 (remove os.environ); compose.py (replace ceremony with factory call); connector.py (declare requires_credentials={'smtp','imap'} + delegate_host_protocol; apply P0-09 seam)
- connectors/slack/.../web_api.py:74,105-106 (remove os.environ); compose.py; connector.py (requires_credentials={'slack'} + delegate_host_protocol; apply P0-09 seam)
- connectors/telegram/.../transport.py:97,130-131 (remove os.environ); compose.py; connector.py (requires_credentials + delegate_host_protocol; apply P0-09 seam)
- connectors/whatsapp/.../cloud_api.py:128,159-161 + webhook.py:69,88-89 + redaction.py:114,144,154 (remove ALL os.environ incl. runtime _hmac_key); compose.py; connector.py (declare the 3 credential classes covering 4 secrets + delegate_host_protocol; apply P0-09 seam) — DEDICATED worktree pass

## Invariants (MUST hold)

- zero os.environ reads remain in any connector package — including whatsapp redaction.py:154 _hmac_key per-message runtime read (host owns from_env via broker; security MEDIUM finding)
- each connector declares requires_credentials (email {smtp,imap}; slack {slack}; telegram {telegram}; whatsapp 3 classes covering 4 secrets) + delegate_host_protocol
- the connector receives BoundTransport handles only — no config/.password/.token reachable
- email injects TWO pre-built transports; whatsapp fronts FOUR secrets across three credential classes and preserves the verified-inbound->window->template-gate data flow + PII-redaction-before-signing floor; whatsapp redact_phone yields a real HMAC under broker injection (not the sentinel)
- compose ceremony replaced by a connector_builder() call (the ~250-LOC hand-copy removed); the P0-09 WIRE seam (raw-key removal + host-owned invocation + ledger/revocation rebind + _sign removal) is folded into each worktree
- whatsapp runs as a DEDICATED worktree pass (no co-scheduled cleanup, not part of a simultaneous fan-out) per capacity MEDIUM finding — its ~7-invariant load does not compete for attention with sibling merges

## Value anchor

Architecture §7 Phase 0: "refactor the 4 references onto all of it". §risk: the 4 references currently self-acquire credentials and would fail a baseline-community safety lint — this refactor makes the canonical examples teach the broker pattern. Brief success criterion: "it cannot see credentials it wasn't granted".

## Acceptance criteria

- [ ] all four connectors read zero os.environ (whatsapp incl. runtime _hmac_key) and compose via connector_builder()
- [ ] each declares requires_credentials + delegate_host_protocol and receives only BoundTransport handles; the P0-09 seam is folded into each worktree
- [ ] all four four-tier test suites pass; whatsapp PII/window/template gates preserved and redact_phone yields a real HMAC; email dual-transport preserved
- [ ] slack lands first; email+telegram parallel; whatsapp as a dedicated worktree pass

## Test plan

Per connector (inside its worktree): grep zero os.environ in the package (whatsapp: incl. redaction.py:154); existing four-tier suites (unit/integration/regression/conformance) pass against the factory+broker composition; whatsapp regression (test_pii_redaction, test_reject_gate_no_send, test_webhook_hmac_boundary) preserved AND redact_phone yields a real HMAC under broker; email both SMTP+IMAP roundtrips via injected BoundTransports; Mailpit/live-double integration unchanged behaviorally. IMPLEMENTATION: slack worktree FIRST (validate the factory+broker+signing+invocation pattern), then email + telegram in parallel worktrees, then whatsapp as a DEDICATED worktree pass. Disjoint packages, no shared version owner.
