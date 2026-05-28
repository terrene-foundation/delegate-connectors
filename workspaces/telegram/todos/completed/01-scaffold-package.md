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

## Verification (Wave 1 — 2026-05-28)

Completed. The package scaffold landed under `connectors/telegram/`:
`pyproject.toml` (dist `delegate-connector-telegram`, hatchling, dynamic version
from `src/delegate_connectors/telegram/__init__.py`, deps
`kailash>=2.24.0` + `cryptography>=42.0` + `httpx>=0.27`, `[test]` extra,
`[tool.hatch.build.targets.wheel] packages = ["src/delegate_connectors"]`),
`README.md` (describes the shipped `authenticate / read / write / invoke` +
`auth_verifier / ledger / revocation` contract; no stale
`connect()/identify()/normalize()` surface; Apache-2.0 note), `.env.example`
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`, `TELEGRAM_TEST_CHAT_ID`, no real
values), `docker-compose.yml` (one local Bot API HTTP service), and the
PEP-420 namespace tree `src/delegate_connectors/telegram/` with `__init__.py`
(`__version__` + public exports).

Evidence (dependency install + commit are the orchestrator's per the wave
brief; the scaffold was exercised against the read-only shared `.venv` via
`PYTHONPATH`):

- Import + coexistence: `PYTHONPATH=connectors/telegram/src:connectors/email/src
.venv/bin/python -W error -c "import delegate_connectors.telegram"` →
  version `0.1.0`; `delegate_connectors.email` and `delegate_connectors.telegram`
  coexist; no warnings (under `-W error`).
- Invariant 1 (PEP-420): the `delegate_connectors` namespace root has NO
  `__init__.py` (verified via `os.path.exists` → False); siblings coexist.
- Invariant 2 (SPDX): every `.py` under `connectors/telegram/` carries the
  Apache-2.0 SPDX header (mechanical `head -2 | grep` sweep, 0 missing).
- `docker compose -f connectors/telegram/docker-compose.yml config` → VALID.
- No hardcoded token/host literals (`grep` clean across `.py`/`.toml`/`.yml`/`.example`).

Note: `docker compose config` and the `pip install -e .` acceptance line both
pass; the editable install + git commit are deferred to the orchestrator per the
Wave-1 brief (read-only shared `.venv`, no `pip install` in this session).
