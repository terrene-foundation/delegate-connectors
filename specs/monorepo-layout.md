# Spec — Monorepo Layout

Per README: each `connectors/<channel>/` is a fresh Python package implementing the
`Connector` interface. v0 establishes the layout with `connectors/email/`.

## Package shape

```
connectors/email/
├── pyproject.toml              # dist: delegate-connector-email; hatchling backend
├── README.md                  # connector-specific
├── src/
│   └── delegate_connectors/    # PEP 420 namespace package (NO __init__.py at namespace root)
│       └── email/
│           ├── __init__.py
│           ├── connector.py    # EmailConnector(Connector)
│           ├── smtp.py         # outbound transport
│           ├── imap.py         # inbound transport
│           └── directory.py    # PrincipalDirectory wiring / resolution
├── tests/
│   ├── conftest.py             # Mailpit fixture
│   ├── unit/
│   ├── integration/
│   └── conformance/            # gated — see conformance.md
└── docker-compose.yml          # mailpit service
```

## pyproject essentials

- `name = "delegate-connector-email"`, dynamic version.
- `dependencies = ["kailash>=2.24.0"]` (delegate shipped 2.24.0; dev pins 2.26.2).
- `[tool.hatch.build.targets.wheel] packages = ["src/delegate_connectors"]`.
- Namespace: `delegate_connectors.email` (PEP 420 implicit namespace — siblings like
  `delegate_connectors.slack` coexist without collision).
- License: `Apache-2.0`; SPDX header on every source file.

## Repo-level

- No root `pyproject.toml` today; v0 may add a workspace root or keep per-connector
  packages independent. v0 decision: per-connector independent packages (no root
  workspace) — simplest; matches "each connectors/<channel>/ is a fresh package".
- `kailash>=2.24.0` is the floor (delegate namespace). Dev/CI install 2.26.2.
- Foundation independence: NO dependency on the proprietary Rust sibling.
