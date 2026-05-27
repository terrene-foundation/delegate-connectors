# Architecture — Telegram Connector (v0)

Implementation architecture for the Telegram connector. Grounded in shipped
kailash 2.26.2 (introspected via `.venv/bin/python`) and the analysis docs in
`workspaces/telegram/01-analysis/`. Inherits the shared SDK ADRs from the email
connector (ADR-1..5); decides the channel ADRs (T1..T5). Package shape mirrors
`connectors/email/` exactly per `specs/monorepo-layout.md`.

## ADRs (channel-specific; shared ADR-1..5 inherited, see synthesis)

- **ADR-T1**: inbound = long-polling (`getUpdates`); webhook out-of-scope. The
  one-shot `getUpdates` request-response maps 1:1 onto the audited read thunk;
  webhook needs a framework-first-blocked inbound server + queue-drain restructure.
- **ADR-T2**: outbound = `sendMessage`; v0 `parse_mode` default = plain text;
  validation at the message-construction boundary (control-char reject, text ≤
  4096 UTF-16 units, `chat_id` shape). HTML/MarkdownV2 escaping out-of-scope.
- **ADR-T3**: `authenticate` resolves by `delegate_id`; resolver dual-keyed by
  stringified integer `user_id` + `chat_id`. `@username` is never a key (mutable +
  ref-unsafe). Unknown → fail-closed `Reject`.
- **ADR-T4**: Tier 2/3 real-infra = local Bot API HTTP service (hermetic
  surrogate, real socket); optional secret-gated live-bot path; MTProto rejected.
- **ADR-T5**: rate-limit `429`/`retry_after` surfaced as typed error; retry/backoff
  deferred to caller (retry-under-audit would multiply `SignedActionEnvelope`s).

## ABC-member mapping (TelegramConnector → shipped Connector)

| ABC member                               | Telegram behavior                                                                                                                                                                       |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate(identity, envelope)`       | Resolve `str(identity.delegate_id)` to a `Principal` against the dual-keyed resolver. Unknown → `ConnectorAuthenticationError` (closed-enum `Reject`, fail-closed).                     |
| `write(action, *, identity, envelope)`   | `action` is a thunk wrapping a Bot API `sendMessage` POST. Run under audit; return `SignedActionEnvelope` over FULL identity (signer + action_id + observed_at).                        |
| `read(query, *, identity, envelope)`     | `query` is a thunk wrapping a Bot API `getUpdates` GET. Run under audit; return `(updates, AttestedReadReceipt)` over the message-id manifest (no message bodies in the payload).       |
| `invoke(payload, *, identity, envelope)` | Hot-path entry. `authenticate` FIRST (fail-closed gate before any Bot API call); then send via the audited `write` path; return `ConnectorInvocationResult(external_side_effect=True)`. |
| `auth_verifier`                          | The supplied `Ed25519Verifier(directory)` (shipped concrete).                                                                                                                           |
| `ledger`                                 | `InMemoryKnowledgeLedger` (Protocol-satisfying deterministic adapter; inherited).                                                                                                       |
| `revocation`                             | `NeverRevokedChannel` (Protocol-satisfying deterministic adapter; inherited).                                                                                                           |

Signing helpers (`build_action_signing_bytes` / `build_read_signing_bytes` /
`verify_action_envelope` / `verify_read_receipt`) are the channel-agnostic
identity-binding helpers — reused from the email connector's contract (signer +
action_id/read_id + observed_at bound into the canonical bytes).

## Package shape (mirrors connectors/email/)

```
connectors/telegram/
├── pyproject.toml              # dist: delegate-connector-telegram; hatchling
├── README.md                   # connector-specific
├── docker-compose.yml          # local Bot API HTTP service
├── .env.example                # TELEGRAM_* template, no real values
├── src/delegate_connectors/    # PEP 420 namespace (no __init__.py at root)
│   └── telegram/
│       ├── __init__.py         # __version__; public exports
│       ├── connector.py        # TelegramConnector(Connector) + signing helpers + adapters
│       ├── transport.py        # httpx-backed sendMessage + getUpdates (no audit logic)
│       ├── directory.py        # dual-keyed resolver + UnknownSenderDisposition
│       └── compose.py          # build_telegram_runtime(...) — DelegateRuntime composition
└── tests/
    ├── conftest.py             # local Bot API service fixture
    ├── unit/                   # Tier 1
    ├── integration/            # Tier 2/3 (_botapi.py reachability gate + e2e xfail)
    ├── regression/             # identity-binding tamper, invoke-authenticates-first, control-char reject
    └── conformance/            # loader.py + test_canonical_set.py (reuse vendored fixture)
```

`pyproject.toml`: `name = "delegate-connector-telegram"`, dynamic version,
`dependencies = ["kailash>=2.24.0", "cryptography>=42.0", "httpx>=0.27"]`,
`[tool.hatch.build.targets.wheel] packages = ["src/delegate_connectors"]`,
namespace `delegate_connectors.telegram` (PEP 420), Apache-2.0, SPDX header on
every source file. NO dependency on the proprietary Rust sibling.

## Shard breakdown (sized per autonomous-execution § Per-Session Capacity Budget)

Each shard ≤500 LOC load-bearing logic / ≤5–10 invariants / ≤3–4 call-graph hops,
describable in ≤3 sentences. Telegram is a transport-substitution lift; most
load-bearing logic is inherited from email's proven shape.

- **Shard 1 — scaffold package** (boilerplate). `pyproject.toml`, namespace dirs,
  `__init__.py`, `.env.example` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_BASE`,
  `TELEGRAM_TEST_CHAT_ID`), README, SPDX headers. ~150 LOC boilerplate; no
  load-bearing logic. (Invariants: namespace is PEP-420 no-root-`__init__`;
  Apache-2.0 SPDX on every file.)
- **Shard 2 — transport.py** (`sendMessage` + `getUpdates` via `httpx`). Config
  from `TELEGRAM_*` env (typed error if absent, no silent default), `OutboundMessage`
  dataclass with construction-boundary validation (control-char reject, length
  bound, `chat_id` shape), structured `SendResult` / `InboundUpdate`, 429
  surfaced as typed error. ~300 LOC. (Invariants: env-only creds, never logged;
  validation covers every send route; 429 not swallowed; no audit logic in transport.)
- **Shard 3 — directory.py** (dual-keyed resolver). `delegate_id` + `user_id` +
  `chat_id` keying; `@username` → un-resolvable; `UnknownSenderDisposition` closed
  enum; unknown → `Reject`. ~150 LOC. (Invariants: 3-way keying symmetric;
  `@handle` never resolves; fail-closed Reject.)
- **Shard 4 — connector.py** (`TelegramConnector(Connector)` + reused signing
  helpers + adapters). 4 methods + 3 properties; `invoke` authenticates FIRST
  before any Bot API call; receipts bind FULL identity. ~350 LOC load-bearing.
  (Invariants: ABC instantiation succeeds; fail-closed gate on hot path; receipt
  identity-binding + tamper-fail; no creds in logs/audit; 5 invariants — at budget.)
- **Shard 5 — compose.py** (`build_telegram_runtime`). `PrincipalDirectory` +
  `Ed25519Verifier` + in-memory `AuditChainEngine` + `TenantScopedCascade` +
  `Role` + `DispatchSurface` + `DelegateRuntime`; real Ed25519 signer; v0
  dispatch signature fixture. ~250 LOC (mostly inherited composition shape).
  (Invariants: real verifier not Null; composition passes R2 gate; async execute.)
- **Shard 6 — Tier 1 unit tests** (feedback-loop shard, may exceed base budget).
  resolver keying, unknown→Reject, construction validation, receipt
  binding+tamper, invoke-authenticates-first, compose-succeeds.
- **Shard 7 — Tier 2/3 + conformance** (feedback-loop shard). `docker-compose.yml`
  local Bot API service + `_botapi.py` reachability gate; outbound arrival +
  inbound round-trip + e2e (xfail-gated on #1182); conformance loader +
  test_canonical_set reusing the vendored fixture (per-vector xfail-gated).

Shards 2/3/4/5 are independent enough to parallelize as a worktree wave of 3 then
1 (each owns a distinct module); Shards 6/7 depend on 2–5.

## Brief corrections

The brief is accurate against shipped reality on every Telegram-specific claim
(long-poll-leaning inbound, dual-key identity question, `parse_mode` surface,
HTTP-only Bot API, single-token auth). Two notes, neither a brief defect:

1. **Brief line 29 ("`runtime.execute()` is async") is CORRECT** and matches the
   re-verified wheel. It contradicts the STALE
   `workspaces/email/01-analysis/00-synthesis.md:30` ("sync"). No correction to
   the brief; the stale surface is the email synthesis, which is out of this
   workspace's write scope (the orchestrator owns cross-workspace reconciliation).
2. **Brief open question #6 (#1035 telegram-specific contract surface):**
   resolved — the README references Telegram only structurally
   (`connectors/telegram/`); #1035 pins NO telegram-specific contract beyond what
   email v0 delivered. Telegram is a pure transport substitution of the shared
   contract.

## For Discussion

1. Shards 2–5 each own one module and could parallelize. Shard 4 (connector) sits
   at exactly 5 invariants — at the budget ceiling. If a sixth invariant surfaces
   during implementation (e.g. group-vs-private resolution precedence), is that the
   signal to split Shard 4, or does the inherited email shape absorb it?
2. The plan reuses email's signing helpers verbatim. If a future refactor moves
   those helpers to a shared `delegate_connectors._common` module, does that
   change the per-connector shard count, and would `refactor-invariants.md` require
   a LOC-invariant test at that extraction?
3. The local Bot API service (Shard 7) is the only genuinely new test-infra
   component vs email. If the OSS surrogate proves heavier than a 2-method HTTP
   stub, is dropping to a minimal hand-rolled deterministic HTTP service still
   "real infra" under `specs/test-infrastructure.md`, or does that cross into the
   mock territory Tier 2/3 blocks?
