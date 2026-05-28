# Todo 01 — Scaffold `connectors/whatsapp/` package

**Implements:** `specs/monorepo-layout.md` (+ `02-plans/02-connector-spec.md` § Transport, § Security — env catalog)
**Type:** Build (boilerplate) · **Capacity:** single shard (boilerplate, no load-bearing logic)

**Value-anchor:** delivers the brief acceptance criterion "package shape matches `specs/monorepo-layout.md` (`connectors/whatsapp/`, namespace `delegate_connectors.whatsapp`); Apache-2.0 SPDX header on every source file; no dependency on the proprietary Rust sibling."

## Do

- `connectors/whatsapp/pyproject.toml` — dist `delegate-connector-whatsapp`, hatchling
  backend, `dependencies = ["kailash>=2.24.0", "httpx>=0.27", "cryptography>=42.0"]`,
  wheel target `src/delegate_connectors`. License `Apache-2.0`.
- PEP 420 namespace `src/delegate_connectors/whatsapp/` (NO `__init__.py` at the
  `delegate_connectors` namespace root; `whatsapp/__init__.py` present with `__version__`).
- `connectors/whatsapp/README.md` (connector-specific, Apache-2.0 note; full contract
  text lands in todo 13).
- `connectors/whatsapp/.env.example` — `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
  `WHATSAPP_GRAPH_VERSION`, `WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`,
  `WHATSAPP_PII_HMAC_KEY`, `WHATSAPP_APPROVED_TEMPLATES` (no real values).
- No `docker-compose.yml` — the Tier-2 surface is an in-process local double (WA-ADR-5);
  the file is intentionally omitted (a future Nexus receiver would add one).
- Apache-2.0 SPDX header on every `.py`.

## Acceptance

- [ ] `cd connectors/whatsapp && ../../.venv/bin/pip install -e .` succeeds.
- [ ] `../../.venv/bin/python -c "import delegate_connectors.whatsapp"` works; namespace
      coexists with the sibling `delegate_connectors.email`.
- [ ] `.env.example` lists all seven `WHATSAPP_*` keys; no real values present
      (`grep` clean for token-shaped literals).

## Verification

Completed in /implement Wave 1 (2026-05-28).

- `connectors/whatsapp/pyproject.toml` created — dist `delegate-connector-whatsapp`,
  hatchling backend, `dependencies = ["kailash>=2.24.0", "httpx>=0.27",
"cryptography>=42.0"]`, `[test]` extra, wheel target `src/delegate_connectors`,
  `[tool.hatch.version]` reads `src/delegate_connectors/whatsapp/__init__.py`.
  License `Apache-2.0`.
- PEP-420 namespace `src/delegate_connectors/whatsapp/` (no `__init__.py` at the
  `delegate_connectors` root); `whatsapp/__init__.py` present with
  `__version__ = "0.1.0"`.
- `README.md` (Apache-2.0 note, Wave-1 status) and `.env.example` (all seven
  `WHATSAPP_*` keys, no values) created. No `docker-compose.yml` (WA-ADR-5).
- SPDX `Apache-2.0` header on every `.py` (verified by scan — 0 missing).
- Namespace coexistence verified: importing both
  `delegate_connectors.whatsapp` (0.1.0) and the sibling
  `delegate_connectors.email` (0.1.0) under one PYTHONPATH succeeds.
- `.env.example` key count = 7, zero populated values (grep clean).

Note: per-package editable install (`pip install -e .`) was NOT run — the brief
forbids `pip install` against the shared `.venv`; the orchestrator installs deps.
Import + namespace coexistence were instead verified via
`PYTHONPATH=connectors/whatsapp/src:connectors/email/src` (the brief's read-only
test path), which is the equivalent acceptance check.
