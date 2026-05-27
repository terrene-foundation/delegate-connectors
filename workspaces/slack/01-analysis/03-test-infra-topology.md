# 03 — Test-Infra Topology + Runtime Composition + Package Layout

> Claim cluster for brief open question #4 (test-infra topology) plus the
> Slack-specific runtime-composition and packaging deltas. Grounded in shipped
> kailash 2.26.2 + the inherited email ADR-2/3/4/5. Every runtime fact below is
> a live introspection against the wheel in the repo-local `.venv`.

## 0. Inherited runtime facts (ADR-2/3) — re-verified, with one correction

The email analysis established the runtime composition; I re-verified the
load-bearing facts against the wheel this session:

| Fact                                            | Verified value (kailash 2.26.2)                                                  |
| ----------------------------------------------- | -------------------------------------------------------------------------------- |
| `Connector.__abstractmethods__`                 | `{authenticate, invoke, read, write, auth_verifier, ledger, revocation}` (4 + 3) |
| `Delegate` is `DelegateRuntime`                 | TRUE (alias)                                                                     |
| `DelegateRuntime.execute` is a coroutine        | **TRUE — `inspect.iscoroutinefunction(...) is True`**                            |
| `execute` signature                             | `(self, input_payload: dict) -> RuntimeExecutionResult`                          |
| `Delegate.compose(...)` / `delegate.run()`      | DO NOT EXIST                                                                     |
| `pact_engine=` param / `kailash-pact` installed | DO NOT EXIST / not installed                                                     |
| Audit backend                                   | in-memory `AuditChainEngine(TrustLineageChain)`                                  |

### Discrepancy found and resolved: `execute()` is ASYNC, not sync

The email cluster docs `01-analysis/02-connector-contract.md` and
`03-runtime-infra-topology.md` describe `runtime.execute(...)` as **synchronous**
("synchronous signature", "NOT await"). The corrected `specs/runtime-composition.md`
(landed PR #5) says `execute()` is an **async coroutine** callers MUST `await`.
**The wheel confirms the corrected spec:** `inspect.iscoroutinefunction(
DelegateRuntime.execute) is True` in kailash 2.26.2. The Slack connector inherits
the CORRECTED fact: `result = await runtime.execute({...})`. The stale "sync"
claim in the email analysis docs is superseded by `specs/runtime-composition.md`

- this re-verification; the Slack connector wires the async form. (This is noted as
  a brief-correction in `02-plans/01-architecture.md` § Brief corrections.)

## 1. Runtime composition for a Slack connector (mirrors `compose.py`)

The object graph is IDENTICAL to email's `build_email_runtime` — only the
connector + its transports + signature change. The composition is connector-
agnostic by design (the brief's thesis: same spine, different transport):

```
SlackConnector(Connector)                       # the deliverable
  ├ slack transport (AsyncWebClient wrapper: chat.postMessage + conversations.history)
  ├ SlackPrincipalResolver (dual-keyed: delegate_id + slack_id)
  ├ signing_key: Ed25519PrivateKey  → receipts verify under the directory
  └ verifier: Ed25519Verifier(PrincipalDirectory(...))
        │
SlackV0Signature   (SignatureContract Protocol: name + input_schema + output_schema)
DelegateIdentity / DelegateConstraintEnvelope.from_genesis(...) / TenantScopedCascade / Role / signer
        │
DispatchSurface(connector, signature, envelope, identity, audit_engine=…, trust_cascade=…, role=…, signer=…, verifier=…)
        │
DelegateRuntime(dispatch_surface=…, audit_engine=…, cascade=…, envelope=…, identity=…, signer=…, posture=L5_DELEGATED)
        │
result = await runtime.execute({...})           # ASYNC (re-verified above)
```

`build_slack_runtime(...)` is the structural twin of `build_email_runtime(...)`:
generate/accept an Ed25519 key, register the public key in a `PrincipalDirectory`
keyed on `delegate_id`, build the in-memory `AuditChainEngine` over a
`TrustLineageChain` genesis, register the dispatch identity as cascade root grantee
with a real Ed25519 grant proof, and wire `DispatchSurface` → `DelegateRuntime`.

### Inherited SDK blocker (ADR-4): the same kailash-py#1182 gate

The end-to-end `runtime.execute()` is gated on the SAME SDK audit-signature bug the
email connector hit (`workspaces/email/journal/0005`, `compose.py` KNOWN SDK
BLOCKER docstring): the runtime's audit-emit signs the event PAYLOAD bytes while
`AuditChainEngine.emit_event` verifies against the FULL entry signing bytes, so
`execute()` returns `phase == "failed"` under any real verifier. This is an SDK bug,
not a connector bug — the connector's OWN `read`/`write` receipts verify correctly.
The Slack connector mirrors email's exact treatment: composition + per-receipt
verification ship and pass NOW; the end-to-end `execute()` assertion is
**strict-xfail** gated on #1182. Do NOT re-litigate; do NOT work around (the
buildable path is the shipped API, and the receipt-level proof is what v0 ships).

## 2. Test-infra topology (open question #4) — the central Slack delta

### Email's real-infra model, and why Slack cannot copy it literally

Email's Tier-2/3 uses REAL mail containers (`specs/test-infrastructure.md`):
Mailpit (SMTP send + REST arrival assertion) + GreenMail (SMTP+IMAP round-trip).
The principle is: **a single reproducible container at the transport boundary, no
mocking the boundary** (`rules/testing.md` Tier-2/3).

Slack has no self-hostable "real Slack server" — Slack is a hosted SaaS. The two
candidate real-infra topologies:

| Option                                                    | What it is                                                                                                                                                                            | Tier-2 fit                                                                                                                                             | CI without manual setup                                                                                                                                         |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. Live workspace + test bot token**                    | A real Slack workspace + a real bot token in `SLACK_BOT_TOKEN`; tests post to a real test channel and read it back via `conversations.history`.                                       | Highest fidelity (real Slack API).                                                                                                                     | NO — requires a per-CI-job manually-provisioned workspace + secret-managed token; not reproducible from a single container; rate-limited; flaky across CI runs. |
| **B. Local Slack Web API mock server (single container)** | A container that speaks the Slack Web API HTTP contract (`chat.postMessage`, `conversations.history`) and records/serves messages — the Slack analogue of Mailpit's REST arrival API. | Good — exercises the real HTTP transport + the connector's real request/response handling against a real socket, no mocking at the connector boundary. | YES — single reproducible container, `docker-compose up`, sub-second start, no per-job manual setup, no live secret.                                            |

### slack-mock candidate survey (honest)

The brief names `slack-mock` (open source) as the candidate. Survey findings:

- The original `slack-mock` (Node) is **stale** (no release in years; targets the
  legacy RTM/old Web API). Per `rules/dependencies.md` (no unmaintained deps), it
  is NOT a safe pick as-is.
- Maintained alternatives that speak the **current** Slack Web API HTTP contract
  and run as a single container exist in the ecosystem (e.g. a small WireMock /
  Prism-backed stub seeded with the `chat.postMessage` + `conversations.history`
  response shapes, or a purpose-built Go/Python stub). The decision is NOT "find a
  blessed off-the-shelf slack-mock"; it is "stand up a single reproducible
  container that serves the two Web API methods v0 uses, with a record/replay
  surface for the arrival assertion" — exactly the role Mailpit plays for email.

### RECOMMENDATION (resolves open question #4): mock-server container for Tier-2 CI; live workspace as an opt-in Tier-3

Mirror email's real-infra preference (`single reproducible container where
possible`) with a Slack-shaped topology:

- **Tier 2 (default, CI-runnable, no manual setup): a single Web API mock-server
  container.** It serves `chat.postMessage` (records the posted message + returns a
  `ts`) and `conversations.history` (returns the recorded messages). The connector
  talks to it over a real `AsyncWebClient` pointed at the container's base URL
  (`AsyncWebClient(base_url=...)` — the SDK supports an override). NO mocking at the
  connector boundary — the connector makes real HTTP calls; only the _server_ is a
  local stub, exactly as Mailpit is a local SMTP server, not a mocked `smtplib`.
  This is `rules/testing.md`'s Protocol-Satisfying-Deterministic-Adapter exception:
  a real HTTP server with deterministic output is NOT a mock.
- **Round-trip** (the GreenMail analogue): post via the mock's `chat.postMessage` →
  read back via the mock's `conversations.history` through the connector's `read`
  path → assert a verifiable identity-bound `AttestedReadReceipt`.
- **Tier 3 (opt-in, NOT default CI): live workspace + test bot token.** Gated
  behind a reachability check (`requires_live_slack`) that SKIPS with a
  "cannot execute" reason when `SLACK_BOT_TOKEN` + a test channel id are absent —
  mirroring email's `requires_mailpit_smtp` / `requires_greenmail` skip-gates.
  This keeps the highest-fidelity check available for a human-run validation pass
  without making every CI job depend on a live workspace.

### Why NOT live-workspace-as-Tier-2 (the trade-off, named)

Live workspace gives the highest fidelity but FAILS the "CI runnable without manual
per-job setup" bar (the email standard): it needs a provisioned workspace, a
secret-managed token per CI job, and is rate-limited + flaky across runs. The
mock-server container gives reproducibility + zero-manual-setup at the cost of
fidelity to Slack's exact edge-case behaviors (rate-limit envelopes, exotic error
codes). v0's job is to prove the connector pattern generalizes — the bounded
post + bounded history-read against a real HTTP transport does that. The fidelity
gap is covered by the opt-in Tier-3 live check, not by making CI fragile.

### docker-compose + reachability gates (mirrors email)

- `connectors/slack/docker-compose.yml`: one service — the Slack Web API mock
  (single container, bound `0.0.0.0`, exposes the base URL the `AsyncWebClient`
  targets).
- `connectors/slack/tests/integration/_slack_mock.py`: `requires_slack_mock`
  reachability gate (skip with "cannot execute" when the container is unreachable);
  `requires_live_slack` gate for the opt-in Tier-3 (skip when token/channel absent).

## 3. Package layout (ADR-5) — mechanical mirror of email

Per `specs/monorepo-layout.md`: `connectors/slack/`, dist
`delegate-connector-slack`, namespace `delegate_connectors.slack` (PEP 420 implicit
namespace — coexists with `delegate_connectors.email` with NO `__init__.py` at the
namespace root), hatchling backend, Apache-2.0 SPDX header on every source file,
`dependencies = ["kailash>=2.24.0", "slack_sdk>=3.27"]` (the floor is the delegate
namespace floor; dev/CI install 2.26.2). `slack_sdk` is a greenfield dependency
declared in the connector `pyproject.toml` (Apache-2.0, foundation-clean — no
proprietary-sibling coupling).

```
connectors/slack/
├── pyproject.toml                 # dist: delegate-connector-slack; hatchling
├── README.md
├── src/delegate_connectors/slack/ # PEP 420 namespace (no __init__.py at root)
│   ├── __init__.py                # exports SlackConnector
│   ├── connector.py               # SlackConnector(Connector)
│   ├── web_api.py                 # AsyncWebClient wrapper: postMessage + history
│   ├── directory.py               # SlackPrincipalResolver (dual-keyed)
│   └── compose.py                 # build_slack_runtime(...)
├── tests/{unit,integration,regression,conformance}/
└── docker-compose.yml             # slack-web-api mock service
```

The conformance fixture is the monorepo-shared one already vendored at repo-root
`tests/fixtures/delegate-conformance/canonical.json` (ADR-4 — REUSE; do NOT
re-source). Slack's conformance harness reuses the same `VendoredConformanceLoader`
pattern email established.

## Citations

- Runtime async fact: live `inspect.iscoroutinefunction(DelegateRuntime.execute)`
  this session; `specs/runtime-composition.md` (corrected PR #5).
- Composition twin: `connectors/email/src/delegate_connectors/email/compose.py`.
- SDK blocker #1182: `connectors/email/.../compose.py` KNOWN SDK BLOCKER docstring;
  `workspaces/email/journal/0005`; `specs/conformance.md` § gated-on-#1182.
- Email real-infra standard: `specs/test-infrastructure.md`; Mailpit/GreenMail
  reachability gates `connectors/email/tests/integration/_mailpit.py`.
- Package shape: `specs/monorepo-layout.md`; vendored fixture `specs/conformance.md`.
