# 03 — Runtime Composition, Real-Infra Test Topology, Monorepo Layout

Claim cluster for brief open questions #4 (real-infra test topology) and #5 (monorepo
layout). All signatures introspected against the installed wheel: **kailash 2.26.2** at
`.venv/lib/python3.12/site-packages/kailash/delegate/`.

> **Scope note:** read-only `/analyze` research. No production code written. Every
> signature below is a live `inspect.signature(...)` against the installed package.

---

## 0. Brief-claim corrections (GATE before /todos)

The brief (and README line 18-25) describe a composition API that **does not exist in the
shipped wheel**. Per `rules/agents.md` § Parallel Brief-Claim Verification, these are
recorded here as the gate before `/todos`:

| Brief / README claim                                                                                            | Shipped reality (kailash 2.26.2)                                                                                                                                                                | Verdict         |
| --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| `Delegate.compose(connectors=[...], directory=..., signature=..., envelope=..., executor=..., pact_engine=...)` | **No `compose` classmethod exists.** `Delegate` is an alias of `DelegateRuntime`; you construct it directly with kwargs.                                                                        | FALSE           |
| `await delegate.run()`                                                                                          | No `run()` method. Entrypoint is **`runtime.execute(input_payload: dict) -> RuntimeExecutionResult`** (synchronous signature).                                                                  | FALSE           |
| `pact_engine=...` argument; "real PACT engine (NO mocks)"                                                       | **No `pact_engine` parameter anywhere.** `kailash-pact` is NOT installed; `kailash.pact` does not exist. PACT appears only as docstring D/T/R references in `types.py:562-569`.                 | FALSE           |
| "real Postgres audit (NO mocks)"                                                                                | Audit backend is **in-memory** (`TrustLineageChain` dataclass). No `psycopg`/`sqlalchemy` import in the delegate package. Postgres is named once as a docstring aspiration (`dispatch.py:348`). | FALSE           |
| README l.18-25 `connect()/identify()/authenticate()/normalize()`                                                | Stale — same finding the brief already flags. Real ABC = `authenticate/invoke/read/write` + 3 properties.                                                                                       | CONFIRMED-stale |

**Implication for #1035 acceptance:** the "real PACT engine + real Postgres audit" line in
the acceptance criteria is **not satisfiable against the shipped 2.26.2 API** as written —
there is no PACT engine arg and no Postgres audit backend in `kailash.delegate`. This must
be reconciled with the user before `/redteam` convergence can claim to meet it. See §2 + §5.

---

## 1. How a connector is actually composed and run

`Delegate` and `DelegateRuntime` are the **same object** (alias — identical member set).
There is no factory; you instantiate the runtime with keyword-only args:

```
DelegateRuntime.__init__(
    self, *,
    dispatch_surface: DispatchSurface,
    audit_engine:     AuditChainEngine,
    cascade:          TenantScopedCascade,
    envelope:         DelegateConstraintEnvelope,
    identity:         DelegateIdentity,
    signer:           Callable[[bytes], str],
    posture:          Posture = Posture.L5_DELEGATED,
) -> None

DelegateRuntime.execute(self, input_payload: dict[str, Any]) -> RuntimeExecutionResult
```

The connector itself is wired one level down, into the `DispatchSurface`
(`kailash.delegate.dispatch`):

```
DispatchSurface.__init__(
    connector:     Connector,                    # <-- the EmailConnector goes here
    signature:     SignatureContract,            # Protocol: {input_schema, output_schema} dict-shaped
    envelope:      DelegateConstraintEnvelope,
    identity:      DelegateIdentity, *,
    audit_engine:  AuditChainEngine,
    trust_cascade: TenantScopedCascade,
    role:          Role,
    signer:        Callable[[bytes], str],
    verifier:      Verifier | None = None,
) -> None
```

### Minimal object graph to stand up ONE connector

```
EmailConnector(Connector)                              # the deliverable
  │
SignatureContract        (Protocol — input_schema / output_schema dicts)
DelegateIdentity(delegate_id: UUID, sovereign_ref, role_binding_ref, genesis_ref, principal_kind)
ConstraintEnvelope (inner) ─► DelegateConstraintEnvelope(inner, genesis_id)
                                  └ or .from_genesis(envelope, DelegateGenesisRecord)
TenantScope.global_()  /  .for_tenant("t1")  ─► TenantScopedCascade(tenant, verifier=Ed25519Verifier|NullVerifier)
GenesisRecord (kailash.trust.chain) ─► TrustLineageChain(genesis, ...) ─► AuditChainEngine(chain, verifier)
Role(role_id: UUID, display_name, scope: RoleScope, lifecycle: RoleLifecycleState, permitted_principal_kinds)
signer: Callable[[bytes], str]   (sign canonical bytes → signature string; kailash.trust.sign_canonical_envelope is available)
verifier: Ed25519Verifier(directory: PrincipalDirectory)  OR  NullVerifier()   (Tier-1)
  │
DispatchSurface(connector, signature, envelope, identity, audit_engine=…, trust_cascade=…, role=…, signer=…, verifier=…)
  │
DelegateRuntime(dispatch_surface=…, audit_engine=…, cascade=…, envelope=…, identity=…, signer=…, posture=L5_DELEGATED)
  │
result = runtime.execute({...})   # NOT await; NOT .run()
```

**Required args (no defaults) to stand up a runtime:** `dispatch_surface`, `audit_engine`,
`cascade`, `envelope`, `identity`, `signer`. `posture` defaults to `L5_DELEGATED`.

### Connector base decision (brief open Q #1)

`Connector` ABC abstractmethods = `authenticate, invoke, read, write` + 3 properties
(`auth_verifier, ledger, revocation`). Signatures:

```
authenticate(identity, envelope) -> Principal
invoke(input_payload: dict, *, identity, envelope) -> ConnectorInvocationResult
read(query: Callable[[], Awaitable[T]], *, identity, envelope) -> tuple[T, AttestedReadReceipt]
write(action: Callable[[], Awaitable[Any]], *, identity, envelope) -> SignedActionEnvelope
```

`LegacyInvokeConnector(invoke_callable, *, connector_id=None, connector_kind=None,
requires_capabilities=None)` exists and wraps a bare `async def invoke(...)` into the ABC;
the 6 new abstracts auto-derive. **Recommendation (with cons, per recommendation-quality):**
start from the **direct `Connector` ABC**, not `LegacyInvokeConnector`. Email's value is the
read(IMAP)/write(SMTP) split returning `AttestedReadReceipt` / `SignedActionEnvelope`;
`LegacyInvokeConnector` derives read/write FROM `invoke`, which collapses exactly the split
that makes an email connector worth shipping as the reference. Con: direct ABC = 4 methods +
3 properties to implement vs one callable. That cost is the point — it exercises the full
contract #1035 wants proven. (Final pick belongs to `/todos`; flag for user.)

---

## 2. The "pact_engine" argument (brief open Q #2) — does not exist

- `pip show kailash-pact` → **Package(s) not found.** `import kailash.pact` → `ModuleNotFoundError`.
- No `pact_engine` (or `executor`, or `pact`) parameter on `DelegateRuntime.__init__` or `DispatchSurface.__init__`.
- The trust/verification primitive is `Verifier` (`Ed25519Verifier(directory)` or `NullVerifier()`), wired into `DispatchSurface` and `TenantScopedCascade`. There is no separate engine object.

**Audit backend — in-memory, no Postgres required for Tier-1:**
`AuditChainEngine(chain: TrustLineageChain, verifier: Verifier | None)`. `TrustLineageChain`
is a plain dataclass (`genesis: GenesisRecord`, plus capability/delegation/anchor lists) — a
pure in-memory structure. **No DB is required to emit/verify audit receipts.** A file or
Postgres audit store is NOT part of the `kailash.delegate` runtime composition. (`kailash.trust`
separately ships `InMemoryAuditStore` and `SqliteAuditStore` — both present — but neither is
wired into the delegate runtime; they are a different subsystem.)

**Net:** the runtime is fully exercisable with zero external infra. The only "real
infrastructure" an email connector genuinely needs is the **SMTP/IMAP boundary** — not PACT,
not Postgres.

---

## 3. Real-infra test topology (brief open Q #4)

No `docker-compose*` and no `conftest.py` exist anywhere in the repo (verified — `connectors/`
absent, no root `pyproject.toml`). Greenfield; the test-infra convention must be created.

### What real infra each tier actually needs

| Tier | Real boundary                                      | Container / fixture                                                                                                                  |
| ---- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 1    | None — pure runtime composition                    | In-process: `Connector` + `DispatchSurface` + `DelegateRuntime`, `NullVerifier`, in-memory `TrustLineageChain`. Conformance vectors. |
| 2    | SMTP send + IMAP read                              | **Mailpit** (1 container) — single binary, SMTP `:1025` + IMAP `:1143` + REST/UI `:8025`.                                            |
| 3    | SMTP/IMAP under `Ed25519Verifier` + real directory | Same Mailpit container + `PrincipalDirectory` with real Ed25519 keys; assert receipt verification end-to-end.                        |

### SMTP+IMAP container recommendation (with the cons)

**Recommend Mailpit.** It is the only one of the three candidates that exposes **both SMTP
send AND IMAP read** in a single container (`axllent/mailpit`): SMTP on 1025, IMAP on 1143.

- **MailHog** — SMTP only, **no IMAP**; read-back is via its own HTTP API, not IMAP. Disqualified — the brief's `read` path is explicitly IMAP.
- **GreenMail** (`greenmail/standalone`) — supports SMTP + IMAP + POP3, JVM-based. Viable fallback; con: heavier image, JVM startup latency in CI.
- **Mailpit** — SMTP + IMAP + REST, single static Go binary, sub-second startup. Con: IMAP support is newer than GreenMail's and read-only-ish (fine for our read path); no multi-mailbox ACL story (not needed for v0).

Cons of Mailpit overall: smaller IMAP feature surface than a real Dovecot; if v1 needs IMAP
folders/flags/threading, revisit GreenMail. For v0 outbound-send + inbound-read it is the
lightest real boundary.

### PACT engine + Postgres in CI — NOT needed

Per §2, there is no PACT engine and no Postgres audit in the shipped runtime. CI needs **one
container (Mailpit)**, not three. This materially de-risks `/redteam` convergence (see §6).

### Convergence-blocking dependency — conformance fixture is NOT shipped

`ConformanceVectorLoader.load_canonical()` walks up from its `__file__` looking for
`tests/fixtures/delegate-conformance/canonical.json`. **That fixture is NOT in the wheel** —
calling `load_canonical()` in this repo raises:

```
FileNotFoundError: canonical conformance fixture not found at
.venv/.../site-packages/tests/fixtures/delegate-conformance/canonical.json
```

The acceptance criterion "`validate_vector_set(load_canonical())` green" is **unrunnable
until the fixture is vendored** from `terrene-foundation/kailash-py` into this repo at
`tests/fixtures/delegate-conformance/canonical.json` (README step 2 already anticipates a
vendored + checksum-gated copy). `load_canonical(root=<path>)` accepts an explicit root, so
vendoring + passing `root` is the wiring. This is an **external-dependency gate** on
`/redteam` convergence — flagged below.

---

## 4. Monorepo layout proposal (brief open Q #5)

README §"Planned Connector Layout" is authoritative: `connectors/<channel>/` fresh packages,
`conformance/` vendored vector set, `catalog/index.{json,md}`, matrix CI, per-connector
independent semver (Airbyte/dbt pattern). Concrete proposal for `connectors/email/`:

```
connectors/email/
├── pyproject.toml                 # package: delegate-connector-email
├── README.md
├── LICENSE                        # Apache-2.0 (or symlink to root)
├── src/
│   └── delegate_connectors/
│       └── email/
│           ├── __init__.py        # exports EmailConnector
│           ├── connector.py       # EmailConnector(Connector)
│           ├── smtp.py            # outbound write/invoke (smtplib / aiosmtplib)
│           └── imap.py            # inbound read (imaplib / aioimaplib)
└── tests/
    ├── conftest.py                # Mailpit fixture, vendored-vector loader (root=)
    ├── test_tier1_conformance.py
    ├── test_tier2_smtp_imap.py    # real Mailpit
    └── fixtures/delegate-conformance/canonical.json   # OR repo-root tests/fixtures/...
```

- **Package name:** `delegate-connector-email` (distribution); hyphen matches the Airbyte
  per-connector pattern and the proprietary-sibling naming hint in README.
- **Import namespace:** `delegate_connectors.email` — a PEP 420 **implicit namespace package**
  (`delegate_connectors/` has NO `__init__.py`; each connector package contributes its own
  `email/`, `slack/`, etc. subtree). This lets the four connectors ship as four independent
  distributions that import under one shared `delegate_connectors.*` root. Con: namespace
  packages require build-backend care (no `__init__.py` at the namespace root).
- **pyproject shape (recommended):** `[build-system]` hatchling (lightest for namespace
  packages); `[project] requires-python = ">=3.12"` (the wheel is built for 3.12);
  `dependencies = ["kailash>=2.24.0"]` per brief — note the installed runtime is 2.26.2, so a
  `>=2.24.0,<3` floor is safe. `[project.license] text = "Apache-2.0"`.
- **Apache-2.0 headers:** SPDX line `# SPDX-License-Identifier: Apache-2.0` at the top of every
  `.py`; root `LICENSE` already present (Apache-2.0, Terrene-owned). No dependency on the
  proprietary Rust sibling (independence per README §"Independence From Sibling Repo").
- **Conformance fixture placement:** vendor at **repo-root** `tests/fixtures/delegate-conformance/canonical.json`
  (matches `load_canonical()`'s default walk-up) rather than per-connector, so all connectors
  share one checksum-gated copy — aligns with README §"Shared conformance harness".

---

## 5. Recommendation summary

1. **Connector base:** direct `Connector` ABC (not `LegacyInvokeConnector`) — preserves the
   read/write split that is the connector's reason to exist. (User-gate at `/todos`.)
2. **Runtime composition:** construct `DispatchSurface` → `DelegateRuntime` directly; there is
   no `compose()`/`run()`. Entry = `runtime.execute(dict)`.
3. **Infra:** ONE container — **Mailpit** (SMTP+IMAP). No PACT engine, no Postgres.
4. **Layout:** `connectors/email/` → `delegate-connector-email` dist, `delegate_connectors.email`
   namespace, `kailash>=2.24.0`, Apache-2.0 SPDX headers, hatchling.

## 6. External-infra / convergence-risk flags

- **`/redteam` convergence depends on vendoring the conformance fixture.** `load_canonical()`
  raises `FileNotFoundError` today; the canonical vectors are NOT in the 2.26.2 wheel. Until
  `tests/fixtures/delegate-conformance/canonical.json` is vendored from kailash-py (README
  step 2), the "vectors pass" acceptance criterion is unrunnable. This is the single hard
  external dependency.
- **#1035 acceptance ↔ shipped API mismatch (NEEDS USER RECONCILE).** Acceptance says "real
  PACT engine + real Postgres audit (NO mocks)". The shipped `kailash.delegate` runtime has
  **no PACT engine arg and no Postgres audit backend** — audit is in-memory
  (`TrustLineageChain`). Either (a) the acceptance line is aspirational/inherited from the
  proprietary-spine criteria and should be relaxed for the OSS connector, or (b) "PACT engine"
  means the `Verifier`/`TenantScopedCascade` trust primitives (which ARE real and wired). My
  reading is (b) + the audit line is over-specified. Flag to user before `/redteam` claims
  convergence against it.
- **Mailpit is the only real external infra** and is trivially CI-provisionable (single
  container, sub-second start). This does NOT block convergence — unlike the fixture.

```

```
