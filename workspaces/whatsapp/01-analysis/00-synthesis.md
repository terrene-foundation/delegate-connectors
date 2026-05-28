# Analysis Synthesis — WhatsApp Connector (grounded in shipped kailash 2.26.2)

Reconciles `01-transport-topology.md`, `02-identity-template-window.md`,
`03-connector-contract-mapping.md` (2026-05-27). Every claim is grounded in
introspection of the shipped wheel (repo-local venv) and the live Meta Cloud API
surface, NOT the README or issue #1035 prose. Inherits the email v0 ADRs (ADR-1
direct `Connector` subclass; ADR-2 `DelegateRuntime`+`DispatchSurface`; ADR-3
in-memory audit + `Ed25519Verifier`, no Postgres/PACT; ADR-4 vendored conformance
set, xfail-strict per-vector; ADR-5 monorepo layout) and adds the channel-specific
ADRs below.

## Channel ADRs (WhatsApp-specific decisions)

### WA-ADR-1: Production transport is the first-party Meta Cloud API; aggregators are test-only-forbidden

The SHIPPED code path targets `POST https://graph.facebook.com/v{ver}/{PHONE_NUMBER_ID}/messages`
with `Authorization: Bearer <token>` and a `{messaging_product:"whatsapp", ...}`
body — Meta's first-party Graph endpoint. NO third-party aggregator SDK (Twilio,
Vonage) appears anywhere in the shipped connector. The async HTTPS client is
`httpx.AsyncClient` (dumb data transport, framework-first — no custom HTTP
client/router). This is the foundation-independence decision: the connector is
Apache-2.0 Foundation-owned; the network endpoint is unavoidably commercial
(Meta), which is acceptable and stated openly — exactly as email's SMTP host is
a commercial provider. The independence line is: no commercial _intermediary
vendor_ is coupled into the code; the gateway-of-record is the platform's own
first-party API. (Full disposition in the GAP journal entry + the spec Security
section.)

### WA-ADR-2: Inbound is webhook-push; `read`'s thunk drains a connector-owned ingest buffer

WhatsApp has no poll/fetch inbound API. v0 ships an in-process inbound buffer
fed by a connector-owned **webhook ingest protocol** (verify-token handshake +
`X-Hub-Signature-256` HMAC check + envelope parse), drained by the one-shot
`read` thunk. v0 does NOT ship a running HTTP server — owning the public
TLS-terminated socket is a deploy/external-dependency concern. If a reference
receiver is ever added, framework-first REQUIRES it be a Nexus surface, not raw
FastAPI/Flask (flagged GAP, not v0). The ingest protocol (the security boundary
turning an unverified payload into a buffered, verified message) IS in scope; an
unverified webhook payload MUST NEVER reach the audit path.

### WA-ADR-3: Phone number (E.164) is the directory key; ALL phone/`wa_id` identifiers are PII and MUST be redacted in the audit payload

Directory keys on normalized E.164 (mirror of email's `normalize_address`);
`authenticate` resolves by `delegate_id` (the shipped `DelegateIdentity` ref
fields are `^[a-zA-Z0-9_-]+$`-validated and cannot carry a `+`-prefixed number).
A `redact_phone()` helper produces a stable salted-HMAC token `wa:<hmac8>`
(`WHATSAPP_PII_HMAC_KEY` from `.env`); the redacted token — never the raw
number — enters every audit `manifest`/`payload`, ledger record, and log line. A
redaction failure returns the grep-able sentinel `<unredactable wa identity>`,
never the raw number (mask-helper contract). This is a BINDING security
requirement, not optional.

### WA-ADR-4: Template-not-approved AND outside-24h-window are typed `Reject`s at the boundary, pre-flight, before any side effect

`invoke` gates in order: (1) fail-closed `authenticate` (unknown →
`ConnectorAuthenticationError`); (2) template/window pre-flight —
`TemplateNotApprovedError` if a named template is not in the connector's
approved allowlist, `OutsideServiceWindowError` if a free-form send targets a
recipient whose 24h window is closed. Both raise BEFORE the HTTPS POST; Meta's
own error codes are mapped as defense-in-depth backstop. No silent send failure;
no swallowed error.

### WA-ADR-5: Tier 2 runs against a local protocol-faithful Meta Cloud API double; live Meta sandbox is optional Tier 3

The Tier-2 "real infrastructure" is the HTTP protocol itself: a deterministic
in-repo HTTP responder speaking the EXACT Meta wire contract (Bearer auth,
`messaging_product:"whatsapp"` body, `wamid`/`wa_id` response). It is a
Protocol-Satisfying Deterministic Adapter (`testing.md` Tier-2 carve-out), NOT a
mock — the real connector talks to it over a real socket via the real `httpx`
client. CI runs Tier 1 + Tier 2 green with zero per-job account provisioning.
The live Meta sandbox e2e is an OPTIONAL Tier 3 test, skipped with a
"cannot execute" reason when `WHATSAPP_*` live credentials are absent (mirror of
email's container-reachability skip gates).

## Brief corrections (claims diverging from shipped reality)

1. **`runtime.execute()` is ASYNC, not sync.** Introspection:
   `inspect.iscoroutinefunction(DelegateRuntime.execute) is True` on kailash
   2.26.2. The corrected spec `specs/runtime-composition.md` (PR #5) is RIGHT;
   the email synthesis ADR-2 line ("sync, not async") is STALE and must NOT be
   propagated. The WhatsApp connector + e2e harness MUST `await
runtime.execute(...)`. (Journal DISCOVERY 0001.)
2. **Brief leans "Cloud API default" but is soft on aggregators.** The brief
   open-question #1 frames Cloud-API-vs-aggregator as a trade-off ("aggregator =
   simpler sandbox, vendor coupling"). Grounded against `independence` (CLAUDE.md
   Directive 0 + the brief's own #7), the SHIPPED path MUST be Cloud API
   first-party; an aggregator is NOT an acceptable production transport even as a
   default-lean. v0 hard-decides Cloud API (WA-ADR-1). The aggregator is not even
   the test surface — a local protocol double is (WA-ADR-5), so no vendor
   coupling enters the repo at all.
3. **Brief criterion "inbound message read via webhook returns a signed
   `AttestedReadReceipt`" implies the connector hosts the webhook.** It does not.
   v0's connector owns the verify+parse ingest protocol and the buffer the `read`
   thunk drains; it does not own the HTTP listener (WA-ADR-2). The acceptance
   criterion is met by: webhook payload → ingest protocol verifies + buffers →
   `read` thunk drains → signed `AttestedReadReceipt`. The "via webhook" clause
   is satisfied at the ingest-protocol boundary, not by a shipped server.

No other brief claim diverges from shipped reality; the inherited email ADRs all
hold for WhatsApp.

## What IS fully determined (no blocker)

The connector (`authenticate`/`read`/`write`/`invoke` + 3 trust properties
against the real shipped types), the receipt identity-binding helpers, the PII
redaction helper, the template/window pre-flight gates, the `httpx`-based Cloud
API transport, the webhook ingest protocol (verify + HMAC + parse → buffer), the
runtime wiring (`await runtime.execute`), the local-double Tier-2 integration
tests, and the package layout are ALL buildable now against the shipped API.

## What is gated / out of scope

- **Gated on kailash-py#1182** (carry-forward from email): per-vector conformance
  outcome assertion + end-to-end `runtime.execute()` outcome — strict-xfail until
  the audit-emit signing-bytes bug ships. The ABC-composition + well-formedness
  conformance harness ships ACTIVE.
- **Out of v0 scope (bounded, NOT gaps):** a running HTTP webhook receiver (a
  Nexus reference surface is a later shard); durable per-recipient window-state
  persistence (v0 is in-memory); template authoring/management; media /
  interactive / location / contact / sticker messages; live Meta sandbox in CI.

## Blocker requiring user awareness (not a hard blocker)

- \*\*Live e2e against Meta requires a verified business account + permanent token
  - a registered test recipient — provisionable only by a human, not in CI.\*\*
    v0 does not block on this: Tier 1 + Tier 2 (local double) deliver the full
    connector-contract coverage; the live Meta e2e is an opt-in Tier 3 gated on
    `.env` credentials. This mirrors email's posture (Mailpit/GreenMail cover the
    contract; live providers are opt-in). Surfaced as journal GAP 0003 so the
    independence + credential-provisioning tension is explicit, not hidden.
