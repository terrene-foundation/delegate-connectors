# Delegate Connectors

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/lang-Python-3776AB.svg" alt="Python">
  <img src="https://img.shields.io/badge/status-scaffolded%2C%20pre--connector-orange.svg" alt="scaffolded, pre-connector">
</p>

<p align="center">
  <strong>OSS Python connectors monorepo for the Terrene Delegate substrate.</strong><br>
  Reference implementations of <code>kailash.delegate</code> connectors (WhatsApp, email, Slack, Telegram). Apache 2.0.
</p>

---

## What This Is

Each `connectors/<channel>/` directory is a fresh Python package implementing the `Connector` ABC from the OSS spine (`kailash.delegate`, kailash 2.26.2). The shipped contract is **4 methods + 3 trust properties** (verified against the installed SDK):

- `authenticate(identity, envelope) -> Principal` — resolve the dispatch identity to a `Principal` against a `PrincipalDirectory`
- `write(action, *, identity, envelope) -> SignedActionEnvelope` — run a write thunk under audit; return a signed action envelope
- `read(query, *, identity, envelope) -> (payload, AttestedReadReceipt)` — run a read thunk under audit; return the value + an attested receipt
- `invoke(payload, *, identity, envelope) -> ConnectorInvocationResult` — the dispatch hot-path entry
- properties: `auth_verifier -> AuthVerifier`, `ledger -> KnowledgeLedger`, `revocation -> RevocationChannel`

Runtime composition uses `DelegateRuntime(...)` + `DispatchSurface(...)` directly (`runtime.execute(payload)`); there is **no** `Delegate.compose(...)`, `pact_engine=`, or `await delegate.run()` — `Delegate` is an alias of `DelegateRuntime`. Audit is in-memory (`AuditChainEngine`); trust verification is `Ed25519Verifier`.

> The earlier `connect() / identify() / authenticate() / normalize()` contract and the `Delegate.compose` / `pact_engine` / `await run()` runtime shape described a pre-implementation design; none of `connect`, `identify`, `normalize`, `compose`, `pact_engine`, or `run` exist in the shipped `kailash.delegate` API. The list above is the verified shipped contract.

Connectors do NOT own dispatch, audit-chain writes, trust gates, classification, or supervisor wiring. Those are spine concerns.

## Status (2026-05-20)

**Scaffolded, awaiting OSS spine to land.** This repository is a reserved org slot prepared from the `kailash-coc-py` template. Connector implementation is **gated on `terrene-foundation/kailash-py#1035`** authoring the `kailash.delegate` primitives + conformance vectors. Until P1' (the OSS spine) lands those vectors, this repo carries the COC discipline harness but no connector code.

## Open-Core Architecture

The Terrene Delegate substrate is open-core. This repository is one of four pieces:

```
                  Terrene Delegate Spec v0 — CC BY 4.0
                        (neutral published spec)
                                  │
              ┌───────────────────┴────────────────────┐
              ▼                                        ▼
       OSS spine                              proprietary spine
       kailash-py::kailash.delegate           kailash-rs::kailash-delegate-*
       Apache 2.0 (issue #1035)               Commercial (issue #988)
              │                                        │
              ▼                                        ▼
      OSS connectors                          enterprise connectors
      delegate-connectors                     delegate-connectors-enterprise
      (THIS REPO)                             (proprietary sibling)
      Apache 2.0                              Commercial
```

- **Spec authority**: Delegate Spec v0 (CC BY 4.0, neutral, published by Terrene Foundation)
- **OSS spine** (`terrene-foundation/kailash-py`): owns the `kailash.delegate` import namespace + authors the conformance vectors (Apache 2.0)
- **Proprietary spine** (`esperie-enterprise/kailash-rs`): ships the accelerator engine as an entry-point backend (Commercial)
- **OSS connectors** (this repo): fresh Python connectors against the OSS spine (Apache 2.0)
- **Enterprise connectors** (sibling, proprietary Rust monorepo): commercial-grade Rust connectors against the proprietary spine

## Independence From Sibling Repo

This repository's connectors are **fresh Python implementations against `kailash.delegate`**, NOT ports or translations of the proprietary Rust sibling. Different language, different license, different target spine. The shared element is the Delegate Spec v0 contract — both implementations independently honor the spec; neither inherits code from the other.

## Planned Connector Layout

Once P1' (OSS spine) lands:

```
delegate-connectors/
├── conformance/           # vector set vendored from kailash-py
├── catalog/index.{json,md}
├── connectors/
│   ├── whatsapp/          # fresh Python package
│   ├── email/             # fresh Python package
│   ├── slack/             # fresh Python package
│   └── telegram/          # fresh Python package
└── .github/workflows/     # matrix CI: changed-connector → build + conformance
```

Per-connector independent semver. Shared conformance harness. N decoupled release trains. Airbyte / dbt pattern.

## Repository Scaffold

Scaffolded from `terrene-foundation/kailash-coc-py` (the Python COC USE template) on 2026-05-20. The scaffold carries:

- `.claude/`, `.codex/`, `.gemini/` — COC artifact set for Claude Code / Codex / Gemini CLI
- `.codex-mcp-guard/` — MCP guard server for non-Bash Codex tool wrapping
- `scripts/` — project-ops scripts (CI, hooks, plugin)
- `tools/` — utility scripts (lint-workspaces, etc.)
- `workspaces/_template/` — workspace pattern for `/analyze`, `/todos`, `/implement`, `/redteam`, `/codify`
- `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` — per-CLI baselines (template defaults; customize when work begins)

When P1' lands and connector implementation starts, the next session in this repo should:

1. Customize `CLAUDE.md` / `README.md` to reflect actual connector authoring (analogous to the rewrite done in `delegate-connectors-enterprise`)
2. Vendor the conformance vector set from `terrene-foundation/kailash-py` (via submodule or pinned copy with checksum-equality CI gate)
3. Scaffold `connectors/` + `catalog/` per the layout above
4. Wire matrix CI on `.github/workflows/`

## License

Apache 2.0 — see [LICENSE](LICENSE). All open-source IP is owned by the Terrene Foundation, fully and irrevocably transferred per the Foundation Constitution.

## Related

- **Spec**: Terrene Delegate Spec v0 (CC BY 4.0)
- **OSS spine**: [`terrene-foundation/kailash-py#1035`](https://github.com/terrene-foundation/kailash-py/issues/1035)
- **Proprietary spine**: `esperie-enterprise/kailash-rs#988` (separate org)
- **Proprietary sibling**: `esperie-enterprise/delegate-connectors-enterprise` (separate org)
- **Python COC template**: [`terrene-foundation/kailash-coc-py`](https://github.com/terrene-foundation/kailash-coc-py) (scaffold source)
