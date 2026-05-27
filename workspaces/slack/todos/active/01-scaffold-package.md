# Todo 01 — Scaffold `connectors/slack/` package

**Implements:** `specs/monorepo-layout.md` (+ `02-plans/02-connector-spec.md` § Transport, § Security)
**Type:** Build (boilerplate) · **Capacity:** single shard (boilerplate, no load-bearing logic; 2 invariants)

**Value-anchor:** brief acceptance "Apache-2.0 SPDX header on every source file; no dependency on the proprietary Rust sibling; package shape matches `specs/monorepo-layout.md` (`connectors/slack/`, namespace `delegate_connectors.slack`)" (`briefs/01-brief.md` § Acceptance criteria).

## Do

- `connectors/slack/pyproject.toml` — dist `delegate-connector-slack`, hatchling
  backend, dynamic version, `dependencies = ["kailash>=2.24.0", "slack_sdk>=3.27.0"]`,
  wheel target `src/delegate_connectors`. NO dependency on the Rust sibling.
- PEP 420 namespace `src/delegate_connectors/slack/` (NO `__init__.py` at the
  `delegate_connectors` namespace root; `slack/__init__.py` present so siblings
  like `delegate_connectors.email` coexist without collision).
- `connectors/slack/README.md` (connector-specific, Apache-2.0 note — body filled
  in todo 10).
- `connectors/slack/.env.example` — `SLACK_BOT_TOKEN`, optional `SLACK_API_BASE_URL`
  (no real values).
- `connectors/slack/docker-compose.yml` — placeholder service entry filled by todo 08
  (the Web API mock-server container).
- Apache-2.0 SPDX header on every `.py`.

## Invariants (2)

1. PEP 420 namespace: no `__init__.py` at `src/delegate_connectors/`; the slack
   namespace coexists with `delegate_connectors.email`.
2. Apache-2.0 SPDX header present on every source file.

## Acceptance

- [ ] `cd connectors/slack && ../../.venv/bin/pip install -e .` succeeds.
- [ ] `../../.venv/bin/python -c "import delegate_connectors.slack"` works; the
      namespace coexists with `delegate_connectors.email`.
- [ ] `grep -rL "SPDX-License-Identifier: Apache-2.0" connectors/slack/src --include='*.py'`
      returns no files (every `.py` carries the header).
- [ ] No occurrence of the Rust-sibling package in `pyproject.toml` dependencies.
