# Todo 01 — Scaffold `connectors/email/` package

**Implements:** `specs/monorepo-layout.md`
**Type:** Build (boilerplate) · **Capacity:** single shard (boilerplate, no load-bearing logic)

## Do

- `connectors/email/pyproject.toml` — dist `delegate-connector-email`, hatchling,
  `dependencies = ["kailash>=2.24.0"]`, wheel target `src/delegate_connectors`.
- PEP 420 namespace `src/delegate_connectors/email/` (NO `__init__.py` at the
  `delegate_connectors` namespace root; `email/__init__.py` present).
- `connectors/email/README.md` (connector-specific, Apache-2.0 note).
- `connectors/email/.env.example` — `EMAIL_SMTP_HOST/PORT/USER/PASSWORD`,
  `EMAIL_IMAP_HOST/PORT/USER/PASSWORD` (no real values).
- `connectors/email/docker-compose.yml` — one `mailpit` service (SMTP 1025, IMAP 1143, UI 8025).
- Apache-2.0 SPDX header on every `.py`.

## Acceptance

- [ ] `cd connectors/email && ../../.venv/bin/pip install -e .` succeeds.
- [ ] `import delegate_connectors.email` works; namespace coexists with future siblings.
- [ ] `docker compose -f connectors/email/docker-compose.yml config` validates.
