# Architecture — WhatsApp Connector v0

Implementation architecture for the WhatsApp connector. Grounded in shipped
kailash 2.26.2 + the live Meta Cloud API surface (verified 2026-05-27). Inherits
email v0 ADR-1..5; adds channel ADRs WA-ADR-1..5 (see
`01-analysis/00-synthesis.md`). Effort is framed in autonomous execution shards,
not human-days.

## ADRs (summary; rationale in 01-analysis/)

| ADR      | Decision                                                                                                                                           |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| WA-ADR-1 | Production transport = first-party Meta Cloud API (`graph.facebook.com/.../messages`, Bearer). No aggregator SDK. `httpx` is the dumb transport.   |
| WA-ADR-2 | Inbound = webhook-push; `read` thunk drains a connector-owned ingest buffer. v0 ships the ingest protocol (verify+HMAC+parse), NOT an HTTP server. |
| WA-ADR-3 | E.164 is the directory key; phone/`wa_id` are PII and MUST be salted-HMAC-redacted in every audit payload / ledger record / log line.              |
| WA-ADR-4 | Template-not-approved + outside-24h-window are typed `Reject`s, pre-flight, before any side effect; Meta error codes mapped as backstop.           |
| WA-ADR-5 | Tier 2 against a local protocol-faithful Cloud API double (Protocol adapter, not a mock); live Meta sandbox is optional Tier 3 gated on `.env`.    |

## Connector ABC-member mapping

| ABC member      | Implementation                                                                                                                                                  |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate`  | `WhatsAppPrincipalResolver.resolve_delegate_id(str(identity.delegate_id))`; unknown → `ConnectorAuthenticationError`.                                           |
| `write`         | `await action()` (the Cloud API POST thunk) → PII-redact recipient in payload → `build_action_signing_bytes` → Ed25519-sign → non-empty `SignedActionEnvelope`. |
| `read`          | `await query()` (drain ingest buffer) → PII-redact sender in manifest → `build_read_signing_bytes` → attest → `(messages, AttestedReadReceipt)`.                |
| `invoke`        | `authenticate` (fail-closed) → template/window pre-flight `Reject` gate → audited `write` send → `ConnectorInvocationResult(external_side_effect=True)`.        |
| `auth_verifier` | supplied `Ed25519Verifier`.                                                                                                                                     |
| `ledger`        | `InMemoryKnowledgeLedger` Protocol adapter; records event_type + PII-redacted payload only.                                                                     |
| `revocation`    | `NeverRevokedChannel` Protocol adapter (v0: always live).                                                                                                       |

## Module layout (mirror of email)

```
connectors/whatsapp/
├── pyproject.toml                  # dist: delegate-connector-whatsapp; hatchling; deps kailash>=2.24.0, httpx>=0.27, cryptography>=42.0
├── README.md
├── src/delegate_connectors/whatsapp/   # PEP 420 namespace (no __init__.py at namespace root)
│   ├── __init__.py                 # exports + __version__
│   ├── connector.py                # WhatsAppConnector(Connector) + receipt helpers + Protocol adapters + ConnectorAuthenticationError
│   ├── cloud_api.py                # outbound transport: httpx POST /messages, config from WHATSAPP_* env (mirror of smtp.py)
│   ├── webhook.py                  # inbound ingest protocol: verify-token handshake + HMAC check + envelope parse + in-process buffer (mirror of imap.py's role)
│   ├── directory.py                # WhatsAppPrincipalResolver (E.164 + delegate_id keyed) + UnknownSenderDisposition (mirror of email directory.py)
│   ├── templates.py                # approved-template allowlist + 24h-window tracker + TemplateNotApprovedError / OutsideServiceWindowError
│   └── redaction.py                # redact_phone() salted-HMAC PII helper + sentinel
├── tests/{conftest.py,unit/,integration/,conformance/}
└── docker-compose.yml              # (none needed — local double is in-process; file omitted unless a future Nexus receiver lands)
```

## Shard breakdown (sized per autonomous-execution § Per-Session Capacity Budget)

Each shard ≤500 LOC load-bearing logic / ≤5–10 invariants / ≤3–4 call-graph
hops, describable in ≤3 sentences. Boilerplate (pyproject, SPDX headers, dataclass
DTOs) does not count against the load-bearing cap. Shards are ordered by
dependency; Shards 1–3 are independent and parallelizable.

### Shard 1 — Transport + redaction (outbound foundation)

`cloud_api.py` + `redaction.py` + pyproject + namespace skeleton. The `httpx`
async POST to `graph.facebook.com/.../messages` (env-only config via
`WhatsAppCloudConfig.from_env`, typed `CloudApiConfigError` on missing config,
nothing logged), a structured `SendResult` (carries `wamid` + `wa_id`), and the
`redact_phone()` salted-HMAC helper + sentinel.
Invariants: env-only credentials; no credential in logs; redaction sentinel
distinct from success; E.164 validation before send. ~350 LOC. Feedback loop:
Tier-1 unit + local-double integration.

### Shard 2 — Directory + Principal resolution

`directory.py`: `WhatsAppPrincipalResolver` (normalized-E.164-keyed +
delegate_id-keyed), `UnknownSenderDisposition` closed enum mirroring
`{Accept, Reject, EscalateToHuman}`, `ResolutionOutcome`. Unknown → `REJECT`
(fail-closed). ~180 LOC. Invariants: symmetric normalization; fail-closed default;
delegate_id resolution path. Mirror of email `directory.py`. Independent of Shard 1.

### Shard 3 — Webhook ingest protocol + buffer

`webhook.py`: verify-token handshake (`hub.challenge` echo iff token matches),
`X-Hub-Signature-256` HMAC verification over the raw body (app secret from `.env`),
inbound envelope parse (`entry[].changes[].value.messages[]` → `InboundMessage`),
and the in-process `asyncio.Queue` ingest buffer with a one-shot drain.
Invariants: unverified payload NEVER buffered; HMAC constant-time compare;
verify-token constant-time compare; sender PII redacted before buffering; window
tracker fed on each inbound. ~420 LOC load-bearing. Independent of Shards 1–2.

### Shard 4 — Template + window pre-flight gates

`templates.py`: approved-template allowlist (seeded from
`WHATSAPP_APPROVED_TEMPLATES` config), per-recipient 24h-window tracker (in-memory
last-inbound map fed by Shard 3's buffer), `TemplateNotApprovedError` +
`OutsideServiceWindowError` (typed `Reject`s). ~200 LOC. Invariants: pre-flight
fires before side effect; free-form-outside-window → Reject; un-approved-template
→ Reject; template send always window-exempt. Depends on Shard 3 (window data).

### Shard 5 — Connector assembly (the load-bearing integration)

`connector.py`: `WhatsAppConnector(Connector)` wiring all four ABC methods + 3
trust properties, the `build_action_signing_bytes` / `build_read_signing_bytes` /
`verify_action_envelope` / `verify_read_receipt` identity-binding helpers (mirror
of email), `InMemoryKnowledgeLedger` + `NeverRevokedChannel` Protocol adapters,
`ConnectorAuthenticationError`. `invoke` orders: authenticate → template/window
gate → audited write. ~480 LOC load-bearing. Invariants (the full set held
simultaneously): fail-closed auth; pre-flight Reject gate; receipts bind full
identity; PII-redacted payloads; non-empty verifiable receipts; tamper fails
verification; trust properties return real concretes. Depends on Shards 1–4.

### Shard 6 — Tier-2 local-double + conformance harness

The protocol-faithful Cloud API HTTP double (in-process `httpx`-compatible
responder), Tier-2 integration tests (send → assert arrival shape; webhook →
buffer → `read` → verifiable receipt; tamper → verify fails), the vendored
`VendoredConformanceLoader` + ABC-composition conformance harness (active) +
strict-xfail per-vector tests (gated on kailash-py#1182), and the e2e
`await runtime.execute(...)` test (strict-xfail). ~450 LOC (mostly test code,
high feedback-loop multiplier). Depends on Shard 5.

## Brief corrections (divergences from shipped reality found in /analyze)

1. **`runtime.execute()` is ASYNC, not sync.** `inspect.iscoroutinefunction(DelegateRuntime.execute) is True`
   on kailash 2.26.2. The corrected `specs/runtime-composition.md` (PR #5) is
   right; the email synthesis ADR-2 "sync" line is stale. The connector + e2e
   harness MUST `await runtime.execute(...)`. (Journal DISCOVERY 0001.)
2. **Aggregator is not an acceptable production OR test transport.** The brief's
   open-question #1 soft-leans "Cloud API default" with aggregator as a trade-off;
   independence hard-decides Cloud API as the sole production path, and the test
   surface is a local protocol double (WA-ADR-5) — so no vendor SDK enters the
   repo at all, not even in tests.
3. **The connector does not host the webhook.** The brief criterion "inbound
   message read via webhook" is met by the ingest protocol + buffer + `read`
   thunk, NOT by a shipped HTTP server (WA-ADR-2). A Nexus reference receiver is a
   later shard, not v0.

## Out of v0 scope (bounded — NOT spec gaps)

Running HTTP webhook receiver (future Nexus surface); durable window-state
persistence; template authoring; media/interactive/location/contact/sticker
messages; live Meta sandbox in CI; LLM-routed responses (dispatch/kaizen concern);
the slack + telegram connectors.

## New GAPs / blockers

- **GAP (independence tension):** the network endpoint is unavoidably commercial
  (Meta). Disposition: acceptable, stated openly in the spec Security section —
  the connector is Apache-2.0 Foundation-owned, no intermediary vendor SDK is
  coupled. (Journal GAP 0002.)
- **GAP (live-e2e credential provisioning):** live Meta e2e needs a human-verified
  business account + permanent token; not CI-runnable. Disposition: optional Tier
  3 gated on `.env`; Tier 1 + Tier 2 (local double) deliver full contract
  coverage. (Journal GAP 0003.)
