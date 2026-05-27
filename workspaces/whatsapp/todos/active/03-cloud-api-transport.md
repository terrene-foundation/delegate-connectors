# Todo 03 — Cloud API outbound transport (Meta first-party, httpx)

**Implements:** `specs/connector-contract.md` § Methods (`write` thunk) (+ `02-plans/02-connector-spec.md` § Transport — Outbound)
**Type:** Build · **Capacity:** single shard (~160 LOC, 3 invariants)
**Depends:** 01, 02

**Value-anchor:** delivers the brief acceptance criterion "Outbound message send via the chosen API … verified to arrive at the destination phone number" — and honors foundation-independence (Meta Cloud API first-party via generic httpx, no aggregator SDK, WA-ADR-1).

## Do

- `src/delegate_connectors/whatsapp/cloud_api.py`:
  - `WhatsAppCloudConfig.from_env()` — loads `WHATSAPP_ACCESS_TOKEN`,
    `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_GRAPH_VERSION`; raises typed
    `CloudApiConfigError` on any missing key. Credentials NEVER hardcoded
    (`rules/security.md`), NEVER logged.
  - `async send(message) -> SendResult` using `httpx.AsyncClient` to
    `POST https://graph.facebook.com/v{version}/{phone_number_id}/messages` with
    `Authorization: Bearer <token>` and a `{"messaging_product":"whatsapp", "to":..., ...}`
    body. Pure transport; NO audit logic here (the connector wraps this in an audited
    thunk — todo 07).
  - `SendResult` carries the WhatsApp message id (`wamid`) + resolved `wa_id`.
  - E.164 validation of the recipient BEFORE the send fires (reuse todo 02's normalizer).

## Invariants (3)

1. Credentials read only from env; absent creds → `CloudApiConfigError`, not a silent default.
2. Returns a structured `SendResult` (`wamid` + `wa_id`) — no bare bool; transport is the
   only place the raw E.164 transits (the outbound HTTPS body), dropped after the send.
3. E.164 validation happens before the network call; invalid recipient → typed error, no send.

## Acceptance

- [ ] Unit (Tier-1): request construction is correct against the in-process local double
      (todo 10) — URL, headers, body shape — with NO real network.
- [ ] Unit: missing any `WHATSAPP_*` transport key → `CloudApiConfigError`.
- [ ] `grep` clean for any hardcoded token / phone-number-id / graph-version literal.
- [ ] No aggregator SDK (Twilio/Vonage) imported anywhere — `httpx` is the only transport dep.
