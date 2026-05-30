<!--
Copyright 2026 Terrene Foundation
SPDX-License-Identifier: Apache-2.0
-->

# Spec — delegate-connector-whatsapp

**Status**: SHIPPED (v0 merged to main)
**Package**: `connectors/whatsapp/` → `delegate_connectors.whatsapp`
**Implements**: the shipped `kailash.delegate.Connector` ABC (kailash 2.26.2)

---

## 1. Purpose

`delegate-connector-whatsapp` is an OSS Python connector for the Terrene Delegate
substrate (`kailash.delegate`). It binds WhatsApp over the first-party **Meta
Cloud API** (`/messages` outbound + verified-webhook inbound) to the shipped
`Connector` ABC, producing real signed receipts that verify under a real
`Ed25519Verifier`. It is the same contract the email + Slack + Telegram
connectors implement, with a Meta Cloud API transport. Pure Python — no
Rust-sibling dependency, and (WA-ADR-1) NO vendor aggregator SDK (Twilio /
Vonage / MessageBird) anywhere in the dependency graph, production code, or
tests: outbound is a generic `httpx` POST against Meta's Graph API.

It subclasses `Connector` **directly** (WA-ADR-1, the mirror of the email /
slack / telegram decision), NOT `LegacyInvokeConnector` (whose proxied
`read`/`write` emit empty, unverifiable receipts). Every receipt this connector
produces is NON-EMPTY and verifies under a real `Ed25519Verifier`
(`connector.py:5-9`, `:251`).

WhatsApp is the largest-surface connector in the repo. Beyond the shared ABC
contract it carries four invariants that no other connector spec documents,
documented as first-class trust properties in §3: a **PII redaction floor**
(phone → `wa:<8hex>`), a **24h service-window gate**, a **template allowlist**,
and an **inbound webhook HMAC boundary over raw bytes**.

## 2. The 4 ABC members

| Member         | WhatsApp binding                                                         |
| -------------- | ------------------------------------------------------------------------ |
| `write`        | Cloud API `/messages` POST thunk, under audit → `SignedActionEnvelope`   |
| `read`         | one-shot drain of the verified-webhook ingest buffer → `(msgs, receipt)` |
| `authenticate` | `delegate_id` → `Principal`; unknown → fail-closed `Reject`              |
| `invoke`       | authenticate-first → template/window Reject gate → audited write path    |

`write` (`connector.py:405-455`) runs a zero-arg async thunk wrapping the Cloud
API send, then signs over the FULL receipt identity (`{payload,
signer_delegate_id, action_id, observed_at}` — `build_action_signing_bytes`,
`:145-168`), so two identical-payload sends produce distinct signed bytes
(distinct `action_id` + `observed_at`). The recipient is PII-redacted via
`_redact_payload` BEFORE the signed canonical bytes are built (`:429`).

`read` (`connector.py:457-499`) runs a thunk draining the in-process ingest
buffer; the audited manifest carries the message `count` + `message_ids` ONLY
(`_read_manifest`, `:606-619`) — never message bodies, never raw sender
`wa_id`s (which are already redacted on the `InboundMessage` dataclass anyway).
It signs over `{manifest, attester_delegate_id, read_id, observed_at}`
(`build_read_signing_bytes`, `:171-190`).

`invoke` (`connector.py:501-569`) authenticates FIRST: an unknown sender raises
`ConnectorAuthenticationError` (fail-closed `Reject`) before any
`OutboundMessage` is constructed and before any Cloud API call fires. It then
constructs the `OutboundMessage` (running its `__post_init__` validation), runs
the template/service-window `TemplateGate.check` pre-flight Reject gate, and
only then dispatches via the audited `write` path. It returns a
`ConnectorInvocationResult(payload, audit_events=(EXTERNAL_SIDE_EFFECT,),
tenant_id_observed, external_side_effect=True)`.

## 3. Trust properties

### 3.1 The shipped trust-property triple (3)

| Property        | v0 binding                                                 |
| --------------- | ---------------------------------------------------------- |
| `auth_verifier` | the supplied real `Ed25519Verifier`                        |
| `ledger`        | `InMemoryKnowledgeLedger` (Protocol-satisfying, in-memory) |
| `revocation`    | `NeverRevokedChannel` (Protocol-satisfying, never-revoked) |

The trust-property concretes (`connector.py:111-142`) are Protocol-satisfying
deterministic data endpoints, NOT custom trust primitives (the SDK ships the
Protocols, not concretes). Signing / verification stays with the shipped Ed25519
stack. The ledger forwards only `event_type` + the **already-PII-redacted**
payload — never the access token, never the raw recipient (`:444`, `:487`).

### 3.2 Sign-only-on-success (NO forged envelope for a rejected send)

The trust-surface invariant just landed in `cloud_api.py:455-470`:
`WhatsAppCloudApi.send` raises `WhatsAppCloudApiError` BEFORE returning when the
Meta `/messages` response lacks a non-empty `messages[0].id`. That raise
happens INSIDE the `_send` thunk (`connector.py:555-561`), and `write` calls
`result_obj = await action()` (`:424`) — which propagates the raise — BEFORE it
ever calls `build_action_signing_bytes` / `self._sign` (`:437-443`). The
connector therefore does NOT forge a signed envelope for a send the Cloud API
rejected: a missing `messages[0].id` (or a non-2xx, or a non-JSON / non-object
response — `cloud_api.py:400-412`, `:457-470`) aborts the write before any
signature is produced and before any ledger record is appended. This is the same
invariant slack/email were just fixed to honor.

### 3.3 PII redaction floor (phone → `wa:<8hex>`) — binding

Phone numbers and `wa_id`s are PII. The binding floor is that NO raw E.164 ever
enters the signed canonical bytes, a ledger record, or a log line — only a stable
salted-HMAC-SHA256 token of the form `wa:<first-8-hex>` (`redaction.py:160-177`).
`redact_phone` is deterministic and key-stable within a process (same raw number
→ same token under a fixed `WHATSAPP_PII_HMAC_KEY`).

- **Audit-payload floor** (`connector.py:575-596`): `_redact_payload` walks the
  top-level write-payload keys; any key in `_PII_PAYLOAD_KEYS` (`{to, wa_id,
from, recipient, phone}`) with a non-empty string value is rewritten to its
  redacted token before the canonical bytes are built (`:429`).
- **Dual-contract key gate** (`redaction.py:11-35`, `:123-144`): the PII HMAC
  key has a **startup-LOUD + runtime-SOFT** contract. The connector constructor
  calls `RedactionConfig.from_env()` (`connector.py:336`), so an installation
  missing `WHATSAPP_PII_HMAC_KEY` REFUSES to start (`RedactionConfigError`). The
  per-message `redact_phone` path stays fail-SOFT: on ANY runtime failure
  (missing key, un-normalizable input) it returns the grep-able sentinel
  `REDACTION_SENTINEL` (`"<unredactable wa identity>"`) — never the raw number,
  never a leaking exception. The startup gate closes the _systematic_
  missing-key case (where every audit row would silently carry the sentinel);
  the sentinel handles the _transient_ single-rotation-glitch case.
- `normalize_e164` (`redaction.py:68-89`) is the shared bare-digit normalizer
  reused by the directory keys, the inbound `wa_id`s, and the outbound
  recipient, so the redaction token is stable across send and receive surfaces.

### 3.4 24h service-window gate

Free-form (non-template) WhatsApp messages are only deliverable inside the
recipient's open 24-hour customer-service window. The connector enforces this
PRE-FLIGHT (WA-ADR-4) so a violation surfaces as a typed `Reject` at the
connector boundary, NOT a silent downstream send failure. `ServiceWindowTracker`
(`templates.py:66-163`) is a bounded-LRU map of normalized-E.164 →
last-inbound epoch seconds, fed by the **verified-inbound path** via
`record_inbound` (the `window_sink` callback the webhook ingest invokes). A
free-form send to a recipient whose window is not open raises
`OutsideServiceWindowError` (`templates.py:202-236`). `SERVICE_WINDOW_SECONDS`
is `24 * 60 * 60`.

Eviction invariants (`templates.py:80-87`): the map is bounded by `max_entries`
(default `100_000`, an L1 memory-growth fix); `record_inbound` never grows it
past the cap (FIFO-by-record-time `popitem(last=False)`); `is_window_open` is a
PURE READ that does NOT mutate ordering (a window check is not "activity");
re-recording a key moves it to the MRU position so a refreshed key is last to
evict. The time source is injectable for deterministic tests.

### 3.5 Template allowlist

A send naming a template NOT in the connector's approved-template allowlist
raises `TemplateNotApprovedError` (`templates.py:62-63`, `:202-223`). An approved
template send is **window-exempt** (allowed regardless of window state).
`TemplateGate` (`templates.py:166-236`) is seeded from
`WHATSAPP_APPROVED_TEMPLATES` (comma-separated, via `from_env_value`); the
allowlist is held as a stripped, non-empty-filtered `set`. The reject message
never echoes the raw recipient number (only the typed error).

### 3.6 Inbound webhook HMAC boundary over RAW bytes

WhatsApp is webhook-push only; v0 owns the ingest PROTOCOL + an in-process
buffer, NOT a running TLS-terminated HTTP server (owning the public socket is a
deploy concern — WA-ADR-2). The ingest is the security boundary that keeps
unverified payloads out of the audit path (`webhook.py:191-264`):

- `verify_signature` (`webhook.py:121-144`) computes the
  `X-Hub-Signature-256` HMAC-SHA256 over the **EXACT raw request bytes**
  received (never a re-serialized form), keyed by `WHATSAPP_APP_SECRET`, and
  compares constant-time via `hmac.compare_digest`. It rejects a missing /
  malformed `sha256=<hex>` header and raises `TypeError` if handed a non-bytes
  body (forcing callers to pass raw bytes, not parsed JSON). This is the
  raw-body discipline `rules/nexus-webhook-hmac.md` mandates: re-serialized JSON
  would never match Meta's on-wire bytes.
- `WebhookIngest.ingest` (`webhook.py:236-264`) verifies the HMAC FIRST; a
  payload that fails is REFUSED — returns `0`, nothing is buffered, nothing is
  audited, and the rejection is logged WITHOUT any payload bytes (they are
  unverified and may carry PII). Only after verification is the body
  JSON-parsed and walked.
- `verify_token_challenge` (`webhook.py:105-118`) echoes `hub.challenge` ONLY on
  a `subscribe` mode with a `hub.verify_token` matching
  `WHATSAPP_WEBHOOK_VERIFY_TOKEN` under a constant-time compare.

## 4. Inbound transport — verified-webhook ingest buffer, not a server (WA-ADR-2)

Inbound is a one-shot drain of an in-process FIFO buffer fed by the verified-
webhook path, NOT a running HTTP server. `parse_inbound_envelope`
(`webhook.py:147-178`) walks `entry[].changes[].value.messages[]` into normalized
`InboundMessage` records. The sender `wa_id` is PII-redacted before it enters any
buffered record; the bare-digit window-tracking key is computed by the parser and
handed DIRECTLY to the `window_sink` callback at ingest-time — it never lands on
the `InboundMessage` dataclass and never enters the buffer (the M1 contract from
the wave-1 security review). Malformed or statuses-only payloads yield an empty
list, never an exception that would surface a raw number. `read` calls
`drain_one` / `drain_all` (`webhook.py:266-279`) — one bounded drain per audited
read receipt.

## 5. Outbound content validation (WA-ADR-1)

`OutboundMessage.__post_init__` (`cloud_api.py:201-220`) is the single
construction-boundary validation, covering EVERY send route (the `invoke` hot
path and any direct `write` / `send` call build an `OutboundMessage` first):

- **Exactly-one-of contract**: a message MUST declare exactly one of `text`
  (free-form) or `template_name`; both-or-neither raises
  `MessageValidationError` (`cloud_api.py:202-209`).
- **E.164 normalization**: `to` is normalized to bare-digit form via
  `normalize_e164`; a value with no digits raises `MessageValidationError`
  BEFORE any byte transits HTTP (`cloud_api.py:213-220`).

`to_body` (`cloud_api.py:222-240`) serializes to the Cloud API JSON shape
(`type: "template"` with `{name, language: {code}}`, or `type: "text"` with
`{body}`). A `429` rate-limit response is surfaced as a typed `RateLimitedError`
carrying `retry_after` (mirrors telegram ADR-T5) — never swallowed, never
retried in-transport; the caller decides backoff (`cloud_api.py:326-373`).
Response bodies are never logged verbatim (they may echo recipient PII); the
typed error carries only the Cloud API's structured description string.

## 6. Identity resolution

`WhatsAppPrincipalResolver` (`directory.py:69-end`) is dual-keyed: it is keyed by
each principal's `delegate_id` (the PRIMARY key `authenticate` consults) AND by
the normalized E.164 phone number (the inbound-sender resolution path). `authenticate`
resolves by `delegate_id` because the shipped `DelegateIdentity` validates its ref
fields against `^[a-zA-Z0-9_-]+$` and therefore CANNOT carry a `+`-prefixed phone
number — the literal phone lives only on the message payload (and is PII-redacted
before audit bytes are built). Resolution is exact-match in v0; both keys are
normalized identically on construction so a phone lookup is symmetric with an
inbound `wa_id`. Unknown identity → fail-closed `Reject` (never `Accept`);
`EscalateToHuman` is reserved for a later policy shard. The closed disposition
enum (`UnknownSenderDisposition`, `directory.py`) mirrors the conformance
`BehaviouralOutcome` enum `{Accept, Reject, EscalateToHuman}`.

## 7. Runtime composition

`build_whatsapp_runtime(cloud_api=…, ingest=…, sender_phone=…,
approved_templates=…, signing_key=…)` (`compose.py:136-292`) composes the full
shipped runtime — `PrincipalDirectory` + `Ed25519Verifier`, in-memory
`AuditChainEngine` over a `TrustLineageChain`, `TenantScopedCascade` (root
grantee registered with a real Ed25519 grant proof), `Role`, `DispatchSurface`,
and `DelegateRuntime` — using spine-shipped concretes for everything except the
connector. No mocks; no Postgres; no PACT (the shipped runtime audit is
in-memory). The composer wires the ingest's `window_sink` to the
`ServiceWindowTracker.record_inbound` in-place (`compose.py:248-254`) so verified
inbounds open the gate's window, and keys the resolver + `Principal.claims` by
the BARE-DIGIT phone form (the raw `+E.164` lives only on the transient inbound
HTTPS body). `WhatsAppV0Signature` (`compose.py:80-114`) is a documented minimal
v0 dispatch signature — genuine, not a production stub.

## 8. Test topology

| Tier        | Backing                                                                                                   |
| ----------- | --------------------------------------------------------------------------------------------------------- |
| Tier-1 unit | pure-Python, no I/O (transport seam stubbed at the SDK boundary)                                          |
| Tier-2/3    | local Cloud API double over a real socket (WA-ADR-5)                                                      |
| Conformance | monorepo-shared canonical vector set; per-vector outcome xfail-gated                                      |
| Regression  | behavioral security guards (NEVER deleted) — e.g. the window-eviction-order + sign-only-on-success guards |

Markers are declared in `pyproject.toml` (`integration`, `regression`,
`conformance`); `asyncio_mode = "auto"`. The connector's own `read`/`write`
receipts verify correctly under the real `Ed25519Verifier` in the Tier-1 suite;
the end-to-end `runtime.execute()` outcome is the strict xfail described in §9.

## 9. Known SDK blocker

`runtime.execute()` is gated on kailash-py#1182 (`compose.py:17-30`): the shipped
`kailash.delegate` runtime audit-emit path signs the event PAYLOAD bytes
(`DelegateRuntime._emit_phase_audit` / the `DispatchSurface.dispatch` audit
loop), while `AuditChainEngine.emit_event` verifies the signature against the
FULL audit-entry signing bytes (`AuditChainEntry.to_signing_bytes()` — sequence +
previous_hash + event_type + event_payload + signer + signed_at). The two byte
strings are never equal, so `emit_event` raises `AuditChainSignatureError` on the
first phase transition and `execute()` returns `taod_state.phase == "failed"`
under ANY real verifier. This is an SDK bug, not a connector bug — the
connector's own `read`/`write` receipts verify correctly, and composition
(everything `build_whatsapp_runtime` does) succeeds. The end-to-end `execute()`
assertion is a strict xfail in the conformance + e2e suites; the connector-level
send → drain round-trip and receipt verification are not gated. Same failure mode
as the email + slack + telegram connectors.

## 10. Configuration

All credentials are env-only (no silent default; a typed error on absence). The
**four** load-bearing WhatsApp credentials refuse-on-absent with the same
`_require_env` shape:

- `WHATSAPP_ACCESS_TOKEN` (required) — the Meta Cloud API Bearer credential.
  Absent → `CloudApiConfigError`. NEVER logged, NEVER in a repr (the config's
  `__repr__` redacts it — `cloud_api.py:170-175`), NEVER on an audit payload.
- `WHATSAPP_PHONE_NUMBER_ID` (required) — the sender phone-number id. Absent →
  `CloudApiConfigError`.
- `WHATSAPP_GRAPH_VERSION` (required) — the Graph API version; a leading `v` is
  stripped so callers can write `"v18.0"` or `"18.0"`. Absent →
  `CloudApiConfigError`.
- `WHATSAPP_APP_SECRET` (required for inbound) — the webhook HMAC key. Absent →
  `WebhookConfigError`.
- `WHATSAPP_WEBHOOK_VERIFY_TOKEN` (required for inbound) — the verify-token
  handshake secret. Absent → `WebhookConfigError`.
- `WHATSAPP_PII_HMAC_KEY` (required) — the PII-redaction salt/key; the
  connector constructor refuses to start if it is absent (`RedactionConfigError`,
  the startup half of §3.3's dual contract).
- `WHATSAPP_APPROVED_TEMPLATES` (optional) — comma-separated approved-template
  allowlist; an empty/unset value means no template is approved (every template
  send is `Reject`ed).

Nothing is hardcoded; nothing sensitive is logged.

**kailash dependency floor**: `pyproject.toml` declares `kailash>=2.24.0` (the
release in which the `kailash.delegate` namespace shipped), but the ABC this
connector implements is verified at **kailash 2.26.2** (dev/CI pins 2.26.2; the
floor is the minimum that carries the namespace, the pin is the verified target).
Consistent with how slack-connector.md handles the same split. The Cloud API base
host is the published Meta endpoint `https://graph.facebook.com`
(`cloud_api.py:69`); the per-call path is
`{base}/v{version}/{phone_number_id}/messages` (`cloud_api.py:307-312`).

## 11. Cross-references

- `specs/connector-contract.md` — the shared ABC contract
- `specs/conformance.md` — the conformance harness + the #1182 gate
- `specs/test-infrastructure.md` — the 4-tier topology
- `specs/slack-connector.md`, `specs/telegram-connector.md`,
  `specs/email-connector.md` — the contract siblings (this connector is the
  fourth implementation of the same ABC)
- `connectors/whatsapp/README.md` — the shipped-contract overview
- `.claude/rules/nexus-webhook-hmac.md` — the raw-body HMAC discipline §3.6 honors
