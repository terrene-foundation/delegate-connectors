# Brief — WhatsApp Connector (v0)

> **Provenance:** Agent-drafted 2026-05-27 under `/autonomize` after the email
> connector v0 shipped + `/redteam` re-validation CONVERGED. The user-stated
> directive was "all 3 for F3 in parallel" (slack/telegram/whatsapp), so this
> brief opens the whatsapp track. Pattern lift from `workspaces/email/briefs/01-brief.md`.
> **User amendment expected** — flag anything mis-scoped.

## Goal

Ship the fourth OSS Python connector in this monorepo: a **WhatsApp connector**
that implements the `kailash.delegate.Connector` contract. v0 is the third
pattern lift after email — same ABC, same audit-receipt shape, different
transport. WhatsApp is the **heaviest** of the three F3 channels (Meta-owned
API, verified-business-account requirement, webhook-only inbound, message
template approval for outbound to new users), so `/analyze` will likely
surface the largest scope-bounding decisions.

## What's known (cross-channel invariants — reuse from email v0)

Identical to the slack + telegram briefs — repeated here so each workspace is
self-contained:

- Base class is the shipped `Connector` ABC directly (ADR-1 from email v0).
- Required members: 4 methods + 3 properties.
- Trust + audit: spine-shipped `Ed25519Verifier`, `PrincipalDirectory`,
  `AuditChainEngine`, `TenantScopedCascade`.
- Receipts: bind FULL identity (signer + action_id + observed_at).
- `runtime.execute()` is async; kailash-py#1182 gates the e2e.
- Credentials env-only (`WHATSAPP_*`); no hardcoded secrets; nothing logged.

## v0 Scope — channel-specific shape

**In scope:**

1. A `WhatsAppConnector` implementing the shipped `Connector` contract directly.
2. **Outbound** — send a WhatsApp message as the `write`/`invoke` action.
   Transport options for `/analyze`: **WhatsApp Cloud API** (Meta Graph API,
   POST `/messages`) vs **on-prem Business API** (deprecated by Meta) vs a
   **third-party aggregator** (Twilio, Vonage, etc.). v0 default lean: Cloud
   API (Meta's first-party path).
3. **Inbound** — read messages as the `read` path. WhatsApp is **webhook-only**
   for inbound (no polling equivalent), so the connector needs an inbound HTTP
   endpoint. Question for `/analyze`: where does the webhook receiver live?
4. `authenticate()` resolves a WhatsApp identity (phone number in E.164
   format, or `wa_id`) to a `Principal`. Unknown → fail-closed `Reject`.
5. Message-template constraint: Meta requires pre-approved templates for
   outbound to users who haven't messaged in 24h. v0 contract MUST surface
   this constraint clearly (likely a `Reject` disposition for "template
   not approved" at the connector boundary, NOT a silent send failure).
6. Tier-1 unit + Tier-2/3 integration tests against a real-infra surrogate.
   The most plausible real-infra option is **Meta's sandbox business
   account** (free dev tier) OR a **Twilio WhatsApp sandbox** (also free
   dev tier) — `/analyze` decides which is more reproducible in CI.

**Out of scope (v0 — do not chase):**

- Message templates beyond a single approved baseline (no template authoring
  workflow inside the connector).
- Media (image / document / audio / video), location, contact, sticker,
  interactive messages (lists, buttons, flows).
- WhatsApp Business Platform UI (template manager, message scheduling, broadcast).
- Encryption beyond what the transport provides (E2EE is Meta-handled).
- LLM-routed responses inside the connector (dispatch/kaizen concern).
- The other two connectors (slack, telegram).

## Acceptance criteria

- [ ] `WhatsAppConnector` satisfies `kailash.delegate.Connector` ABC — every
      abstract member implemented (ABC instantiation succeeds).
- [ ] Outbound message send via the chosen API verified to arrive at the
      destination phone number (real-infra check, not a mocked client).
      Sandbox account acceptable for v0 e2e.
- [ ] Inbound message read via webhook returns a signed `AttestedReadReceipt`
      that verifies under the shipped `Ed25519Verifier`.
- [ ] `authenticate()` resolves a known WhatsApp identity to a `Principal`;
      unknown → `ConnectorAuthenticationError` (fail-closed Reject) BEFORE
      any API call fires on the `invoke` hot path.
- [ ] Receipts bind FULL identity (signer + action_id + observed_at);
      tamper of any field fails verification.
- [ ] Template-not-approved → typed `Reject` at the connector boundary,
      surfaced cleanly (NOT a silent send failure).
- [ ] All credentials read from `.env`; `.env` git-ignored; no credential in
      any log line or audit payload.
- [ ] Tier-1 unit suite + Tier-2/3 real-infra suite both green; conformance
      harness reuses the monorepo-shared canonical set.
- [ ] Apache-2.0 SPDX header on every source file; no dependency on the
      proprietary Rust sibling; package shape matches `specs/monorepo-layout.md`
      (`connectors/whatsapp/`, namespace `delegate_connectors.whatsapp`).

## Open questions for /analyze

1. **API choice** — Meta Cloud API direct vs a third-party aggregator
   (Twilio, Vonage). Trade-off: direct = cheaper at scale, more setup;
   aggregator = simpler sandbox, vendor coupling. Foundation-independence
   rules out commercial coupling in the SHIPPED code path — but a sandbox
   for testing is acceptable. Which API does the v0 reference implementation
   target as its production path?
2. **Webhook receiver topology** — WhatsApp is webhook-only inbound. The
   `read(query, …)` thunk shape is one-shot; webhook delivery is push.
   Options:
   - In-process queue + a sidecar HTTP server that the connector pulls from.
   - The connector ships ONLY outbound; inbound is a separate "ingest"
     surface (matches dispatch/kaizen layering).
   - The connector defines a webhook-handler protocol and consumers wire it.
3. **Identity model** — phone number (E.164) vs `wa_id` (WhatsApp ID). Both
   are stable; the directory needs a clear primary. Privacy: phone numbers
   are PII — the audit payload MUST NOT carry the raw number unredacted.
4. **Template-approval flow** — Meta requires pre-approved templates for
   24h+ outbound. How does the connector signal "template not approved" —
   typed `Reject` at the connector boundary? Pre-flight check via the
   templates endpoint?
5. **Test-infra topology** — Meta sandbox business account (free, has rate
   limits, requires verified developer) vs Twilio WhatsApp sandbox (free,
   simpler signup, vendor-coupled for the duration of the test only). Which
   does Tier-2/3 use? Can CI use either without per-CI-job manual setup?
6. **24-hour customer-service window** — Meta restricts free-form messages
   to a 24-hour window after the user's last inbound. Does the connector
   enforce this client-side, or rely on Meta's response?
7. **Foundation independence** — the WhatsApp transport is unavoidably
   bound to a commercial gateway (Meta or an aggregator). The CONNECTOR
   itself is Foundation-owned Apache-2.0, but the network endpoint is
   commercial. Document this explicitly in the spec to avoid the
   "commercial coupling" concern under `rules/independence.md`.
8. **#1035 alignment** — does the issue pin any whatsapp-specific contract
   surface beyond what email v0 delivered?
