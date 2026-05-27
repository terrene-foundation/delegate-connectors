# GAP 0002 — Commercial-gateway / foundation-independence tension

Date: 2026-05-27
Phase: /analyze (whatsapp)

## The tension

WhatsApp's transport is unavoidably bound to a commercial gateway. There is no
self-hostable, open WhatsApp network endpoint — the only first-party path is
Meta's Cloud API (`graph.facebook.com`). The connector is Apache-2.0
Foundation-owned, but the network endpoint it talks to is commercial (Meta).

## Why this is not a blocker (disposition)

Same shape as email's SMTP host being a commercial provider: the foundation
independence principle (CLAUDE.md Directive 0; brief #7) forbids coupling the
SHIPPED code path to a commercial _intermediary vendor_ — it does NOT forbid
talking to a platform's own first-party API over a standard protocol.

The decision (WA-ADR-1):

- Production transport = first-party Meta Cloud API only. No third-party
  aggregator SDK (Twilio, Vonage) anywhere in the shipped connector.
- The async client is `httpx.AsyncClient` — a generic HTTP library, not a
  vendor SDK. Swapping the endpoint URL is a config change, not a code change.
- The test surface is a LOCAL protocol-faithful double (WA-ADR-5), so not even
  the test path couples to a commercial vendor.

## What MUST be stated openly (not hidden)

The spec Security section states explicitly: the connector is Apache-2.0
Foundation-owned; the network endpoint is unavoidably commercial (Meta); this is
acceptable and parallels email's commercial SMTP host. The independence line is
"no intermediary vendor SDK in the code," not "no commercial endpoint" (which is
impossible for this channel).

## Status

Resolved as acceptable-and-stated. Carried into `specs/whatsapp-connector.md`
§ Security and `02-plans/01-architecture.md` WA-ADR-1.
