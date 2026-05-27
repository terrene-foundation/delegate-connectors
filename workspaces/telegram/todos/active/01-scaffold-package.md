# Todo 01 — Scaffold `connectors/telegram/` package

**Implements:** `specs/monorepo-layout.md` (+ `02-plans/02-connector-spec.md` § Security)
**Type:** Build (boilerplate) · **Capacity:** single shard (~150 LOC boilerplate, no load-bearing logic)

## Do

- `connectors/telegram/pyproject.toml` — dist `delegate-connector-telegram`, hatchling
  backend, dynamic version, `dependencies = ["kailash>=2.24.0", "cryptography>=42.0",
"httpx>=0.27"]`, `[tool.hatch.build.targets.wheel] packages = ["src/delegate_connectors"]`.
- PEP 420 namespace `src/delegate_connectors/telegram/` (NO `__init__.py` at the
  `delegate_connectors` namespace root; `telegram/__init__.py` present with
  `__version__` + public exports).
- `connectors/telegram/README.md` (connector-specific; describes the shipped
  `authenticate / read / write / invoke` + `auth_verifier / ledger / revocation`
  contract — no stale `connect()/identify()/normalize()` surface; Apache-2.0 note).
- `connectors/telegram/.env.example` — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`,
  `TELEGRAM_TEST_CHAT_ID` (no real values).
- `connectors/telegram/docker-compose.yml` — one local Bot API HTTP service
  (the hermetic surrogate exercised by Tier 2/3 — todo 07).
- Apache-2.0 SPDX header on every `.py`. NO dependency on the proprietary Rust sibling.

## Invariants (2)

1. Namespace is PEP-420 — no `__init__.py` at the `delegate_connectors` root; siblings
   (`delegate_connectors.email`) coexist without collision.
2. Apache-2.0 SPDX header on every source file.

## Acceptance

- [ ] `cd connectors/telegram && ../../.venv/bin/pip install -e .` succeeds.
- [ ] `../../.venv/bin/python -c "import delegate_connectors.telegram"` works;
      namespace coexists with `delegate_connectors.email`.
- [ ] `docker compose -f connectors/telegram/docker-compose.yml config` validates.
- [ ] Every `.py` carries the Apache-2.0 SPDX header.
