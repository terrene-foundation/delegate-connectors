# Todo 09 — Correct README connector-contract section

**Implements:** `specs/connector-contract.md` § Divergence + `journal/0001`
**Type:** Docs · **Capacity:** single shard (small, doc-only)
**Depends:** 05 (so the correction reflects the verified shape)

## Do

- Fix `README.md` lines ~20-23: replace the stale `connect() / identify() /
authenticate() / normalize()` connector contract with the shipped reality:
  `authenticate / read / write / invoke` + `auth_verifier / ledger / revocation`
  properties; runtime via `DelegateRuntime` + `DispatchSurface` (not
  `Delegate.compose` / `pact_engine` / `await run()`).
- Note the open-core positioning is unchanged; only the API description is corrected.

## Acceptance

- [ ] README connector section matches `specs/connector-contract.md`.
- [ ] No remaining reference to `connect()`/`identify()`/`normalize()` or
      `Delegate.compose`/`pact_engine` in README.
- [ ] Ships as a separate doc-only commit/PR (not bundled with connector code).
