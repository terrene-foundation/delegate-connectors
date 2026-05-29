# Todo 13 — Connector README / contract doc

**Implements:** `specs/connector-contract.md` § The interface + § Divergence (+ `02-plans/02-connector-spec.md` § Security — commercial-gateway disposition stated openly)
**Type:** Docs · **Capacity:** single shard (doc-only)
**Depends:** 07 (so the doc reflects the verified shape)

**Value-anchor:** delivers the brief acceptance criterion that the connector ships with an accurate contract description, and the spec's binding requirement to state the commercial-gateway / foundation-independence disposition openly (journal 0002, WA-ADR-1).

## Do

- `connectors/whatsapp/README.md` — describe the SHIPPED connector contract:
  `authenticate / read / write / invoke` + `auth_verifier / ledger / revocation` properties;
  runtime via `DelegateRuntime` + `DispatchSurface` with `await runtime.execute(...)` (async —
  journal 0001). Do NOT carry the stale `connect()/identify()/normalize()` or
  `Delegate.compose`/`pact_engine`/`await run()` shapes.
- State openly: the connector is Apache-2.0 Foundation-owned; the network endpoint is
  unavoidably commercial (Meta Cloud API), which is acceptable and parallels email's commercial
  SMTP host — the shipped path couples to NO intermediary vendor SDK (generic `httpx` against
  Meta's first-party Graph API; endpoint URL is config, not code). (journal 0002.)
- Note v0 scope + out-of-scope (webhook ingest protocol ships, NOT a running HTTP server; a
  reference receiver would be a Nexus surface — out of v0; journal 0003 Gap B).
- Document the seven `WHATSAPP_*` env keys and that `.env` is git-ignored (`.env.example` only).

## Acceptance

- [ ] README connector section matches `specs/connector-contract.md` (no `connect()`/`identify()`/
      `normalize()` / `Delegate.compose` / `pact_engine` references).
- [ ] The commercial-gateway disposition is stated openly (no hidden coupling claim).
- [ ] Ships as a separate doc-only commit/PR (not bundled with connector code).
