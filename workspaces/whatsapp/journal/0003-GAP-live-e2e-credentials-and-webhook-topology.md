# GAP 0003 — Live-e2e credential provisioning + webhook topology decision

Date: 2026-05-27
Phase: /analyze (whatsapp)

## Gap A — live e2e requires human-provisioned credentials, not CI-runnable

A live end-to-end test against Meta requires: a verified business account, a
permanent System-User access token, an app secret, and a registered test
recipient phone number. All are provisionable only by a human (Meta requires a
verified developer); none can be provisioned per-CI-job without manual setup.

Disposition (not a blocker): v0 does NOT block on live Meta access.

- Tier 1 (unit) + Tier 2 (local protocol-faithful Cloud API double, WA-ADR-5)
  deliver full connector-contract coverage and run green in CI with zero per-job
  provisioning.
- The live Meta sandbox e2e is an OPTIONAL Tier 3 test, skipped with a
  "cannot execute" reason when `WHATSAPP_*` live credentials are absent — exactly
  mirroring email's container-reachability skip gates.

## Gap B — webhook topology decision (resolved to WA-ADR-2)

WhatsApp is webhook-push only; the shipped `read(query)` thunk is one-shot/pull.
The decision among the brief's three options:

- (a) in-process queue + sidecar HTTP receiver the connector drains,
- (b) outbound-only connector, inbound as a separate ingest surface,
- (c) connector defines a webhook-handler protocol consumers wire.

v0 ships **(a)+(c) composed**: the connector owns the webhook ingest protocol
(verify-token handshake + `X-Hub-Signature-256` HMAC check + envelope parse) and
an in-process buffer; the `read` thunk drains the buffer. v0 does NOT ship a
running HTTP server — owning the public TLS-terminated socket is a deploy /
external-dependency concern, not a connector-contract concern.

Option (b) rejected: it leaves `read` unimplemented/stubbed, violating the ABC
(read is abstract) and zero-tolerance Rule 2 + the unverifiable-receipt failure
ADR-1 already rejected for the legacy path.

## Framework-first flag for a future shard

IF a reference HTTP webhook receiver is ever added to the repo, framework-first
REQUIRES it be a **Nexus** surface (not raw FastAPI/Flask). This is flagged for a
later shard, explicitly OUT of v0 scope — not a spec gap, a bounded
out-of-scope item.

## Status

Gap A: resolved (optional Tier 3 gated on `.env`). Gap B: resolved (WA-ADR-2).
Both carried into the architecture plan and spec.
