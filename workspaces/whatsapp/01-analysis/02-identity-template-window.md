# Analysis 02 — Identity, Template Approval, 24h Window

Resolves brief open questions #3 (identity model), #4 (template approval), #5
(24h customer-service window), and #6 (test-infra topology). Grounded in the
live Meta Cloud API surface (verified 2026-05-27) and the shipped
`kailash.delegate.dispatch.Principal` / `DelegateIdentity` types.

## Identity model (open question #3) + PII redaction

WhatsApp exposes two stable identifiers:

- **Phone number (E.164)** — e.g. `+6591234567`. The addressing key for an
  outbound send (`to` field). It is **PII**.
- **`wa_id`** — the WhatsApp user id Meta returns in `contacts[].wa_id` on a
  send and in the inbound webhook envelope. Stable per user, opaque, but in
  practice equal to the digits of the phone number — so it is ALSO PII-equivalent
  and MUST be treated as PII.

### Decision: phone number (E.164) is the directory key; `wa_id` is the resolved attribute

Rationale: the consumer addresses a recipient by phone number (it is what they
have); `wa_id` is only known AFTER Meta resolves it. The directory therefore
keys on normalized E.164 (mirror of email's `normalize_address`). This parallels
the email resolver exactly: `WhatsAppPrincipalResolver` maps normalized-E.164 →
`Principal`, and is ALSO keyed by the principal's `delegate_id` (because the
shipped `DelegateIdentity` validates its ref fields against `^[a-zA-Z0-9_-]+$`
and cannot carry a `+`-prefixed E.164 number — the same constraint email hit at
`workspaces/email/journal/0006`). `authenticate` resolves by `delegate_id`; the
literal phone number lives on the message payload.

### PII redaction (BINDING security requirement, not optional)

Phone numbers and `wa_id`s are PII. The audit payload (the `manifest` /
`payload` dict that becomes the signed canonical bytes of an
`AttestedReadReceipt` / `SignedActionEnvelope`) MUST NOT carry the raw number.
The redaction design:

- A pure `redact_phone(e164: str) -> str` helper returns a **stable, salted
  HMAC-SHA256 prefix** form: `wa:<first-8-hex-of-hmac>` (e.g. `wa:3f9c1a20`).
  The HMAC key comes from `WHATSAPP_PII_HMAC_KEY` in `.env` (env-only; never
  hardcoded; never logged). This is the mask-helper contract from
  `observability.md` Rule 6 applied to PII: a parse failure returns a distinct
  grep-able sentinel `<unredactable wa identity>`, NEVER the raw number.
- The redacted token is what enters the audit `manifest`/`payload`, the ledger
  record, and every log line. The raw E.164 lives ONLY in the transient
  outbound HTTPS body to Meta (which is the side-effect, not the audit record)
  and is dropped from memory after the send.
- Receipts still bind FULL dispatch identity (signer `delegate_id` + `action_id`
  - `observed_at`) per the cross-channel invariant — the redaction applies to
    the _message-level_ phone number, not the dispatch-level signer identity.

Why salted HMAC, not truncation/masking: truncation (`+659****567`) still leaks
the country + a partial number and is reversible by brute force over a small
space; a salted HMAC is non-reversible without the key and stable enough to
correlate two audited actions to the same recipient without revealing who.

## Template approval (open question #4)

Meta requires a **pre-approved template** for any outbound message to a user who
is NOT inside an open 24-hour customer-service window. Templates carry a status:
`APPROVED`, `IN_REVIEW` (review takes up to ~24h), `REJECTED`, `PAUSED`,
`DISABLED`. A free-form (non-template) send outside the window, or a template
send naming an un-approved template, is rejected by Meta.

### Decision: typed `Reject` at the connector boundary (pre-flight) — NOT silent send failure

The acceptance criterion is explicit: "template not approved → typed `Reject` at
the connector boundary, NOT a silent send failure." Two enforcement points were
weighed:

- **Pre-flight check** — query the templates endpoint (or a connector-held
  approved-template allowlist seeded from config) BEFORE the send; if the named
  template is not `APPROVED`, raise a typed `TemplateNotApprovedError` (a
  `Reject` disposition) before any HTTPS POST fires.
- **React to Meta's error** — send, then map Meta's template-rejection error
  code to the typed error.

**v0 ships the pre-flight allowlist check** as the primary gate AND maps Meta's
error code as defense-in-depth. Rationale: the fail-closed `Reject`-before-side-effect
discipline (the same shape as unknown-sender Reject on the `invoke` hot path)
requires the rejection to fire BEFORE the external call. A connector-held set of
approved template names (seeded from `WHATSAPP_APPROVED_TEMPLATES` config, or
fetched once at construction from the templates endpoint) lets the pre-flight
gate raise without a network round-trip. The Meta-error mapping is the backstop
for the race where a template's status changed between the pre-flight read and
the send.

`TemplateNotApprovedError` is a typed `Reject` (subclass of the same
`PermissionError` lineage as `ConnectorAuthenticationError`), surfaced cleanly —
NEVER swallowed (`zero-tolerance.md` Rule 3).

## 24-hour customer-service window (open question #5)

The window opens when the user messages the business and resets on each inbound.
Inside it: free-form (non-template) messages are allowed. Outside it: only
templates.

### Decision: client-side enforcement gate, with Meta's response as backstop

v0 enforces client-side: the connector tracks the last-inbound timestamp per
recipient (fed by the webhook ingest buffer, which sees every inbound) and, on
an outbound free-form send, checks whether the window is open. If closed AND the
send is free-form (not a template), the connector raises a typed
`OutsideServiceWindowError` (`Reject`) before the HTTPS POST. A template send is
always permitted (templates are the out-of-window path). Meta's own
out-of-window rejection is mapped as the backstop.

Rationale: same fail-closed-before-side-effect discipline. The window state is
derivable from the inbound buffer the connector already owns; enforcing
client-side turns a silent Meta rejection into a typed, auditable `Reject` at the
boundary. v0 scope-bounds the window tracking to an in-memory per-recipient
last-inbound map (no persistence) — sufficient for the connector contract; a
durable store is a later shard, NOT v0 (and NOT a spec gap — it is genuinely
out-of-scope, bounded explicitly).

## Test-infra topology (open question #6)

Email uses Mailpit + GreenMail — real containers exposing the real SMTP/IMAP
protocol surface, free, CI-runnable with reachability gates. WhatsApp has no
equivalent self-hostable protocol server: the Meta Cloud API is a remote
commercial endpoint, and there is no open-source "WhatsApp server" container.

Candidates:

| Option                                  | CI-runnable without manual per-job setup?                                                                                                                                 | Independence                            |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Meta sandbox business account           | No — requires a verified developer + a test phone number + a manually-provisioned token per environment                                                                   | First-party, but not reproducible in CI |
| Twilio WhatsApp sandbox                 | Partially — simpler signup, but still a per-account token + a one-time join code per test phone                                                                           | Vendor-coupled for the test duration    |
| **Local protocol-faithful HTTP double** | Yes — a deterministic in-repo HTTP responder that speaks the EXACT Meta Cloud API wire shape (Bearer auth, `messaging_product:"whatsapp"` body, `wamid`/`wa_id` response) | Fully independent; no external account  |

### Decision: Tier 1 unit (thunk stubbed at the SDK boundary) + Tier 2 against a local protocol-faithful HTTP double; live Meta sandbox is an OPTIONAL Tier 3 gated on env credentials

Rationale: the email gold standard runs Tier 2/3 against REAL infra
(`testing.md` Tier 2 bans mocks). The honest reading for WhatsApp is that the
"real infrastructure" for an HTTPS/JSON transport is _the HTTP protocol itself_ —
a local server that speaks the exact Meta wire contract is a Protocol-Satisfying
Deterministic Adapter (the explicit `testing.md` Tier-2 carve-out: "a class
satisfying a Protocol at runtime with deterministic output is NOT a mock"). It
exercises the connector's real `httpx` client, real Bearer-header construction,
real body serialization, real response parsing, real `wamid`/`wa_id`
extraction — everything except the remote Meta servers. The live Meta sandbox
e2e is wired as an OPTIONAL Tier 3 test, skipped (with a "cannot execute"
reason) when `WHATSAPP_*` live credentials are absent — exactly mirroring
email's container-reachability skip gates. CI runs Tier 1 + Tier 2 (the local
double) green without any per-job manual account provisioning; the live e2e is a
developer/maintainer opt-in.

This is NOT a stub or a mock of the connector — it is a real HTTP server the
real connector talks to over a real socket. The connector code path is identical
whether the responder is the local double or graph.facebook.com.

Sources (verified 2026-05-27):

- Meta for Developers — message templates overview (status taxonomy: In-Review, Approved).
- Meta for Developers — Sending messages (24h customer-service window; templates are the only out-of-window path).
- Meta for Developers — webhooks messages reference (`wa_id`, inbound envelope).
