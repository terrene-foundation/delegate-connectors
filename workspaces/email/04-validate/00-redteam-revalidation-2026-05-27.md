# /redteam Re-Validation — Email Connector (2026-05-27)

**Posture:** L5_DELEGATED (fresh repo; `posture.json` not materialized → SessionStart default).
**Mode:** full convergence run requested by user (`/autonomize` + `/redteam` to convergence).
**Verifier:** direct executable verification against shipped kailash 2.26.2 + live Mailpit/GreenMail
containers (parallel red-team agents were attempted but the delegation API returned server-side
rate-limit / 529-overloaded; direct adversarial verification against real code+infra was used
instead — stronger evidence than LLM-judgment for security-critical paths).

## Convergence verdict: CONVERGED ✓

| Criterion                              | Result                                                                                                                |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 0 CRITICAL                             | ✓                                                                                                                     |
| 0 HIGH                                 | ✓                                                                                                                     |
| 2 consecutive clean rounds             | ✓ (Round 2 + Round 3)                                                                                                 |
| Spec compliance 100% AST/grep verified | ✓ (table below)                                                                                                       |
| New code has new tests                 | ✓ (every module imported by ≥3 test files)                                                                            |
| 0 mock data                            | ✓ (Tier-2/3 real infra; in-memory adapters are Protocol-satisfying deterministic adapters per `testing.md` carve-out) |

**Findings:** 1 total — MEDIUM spec-accuracy defect (journal 0011), **fixed this run**. 0 remaining.

## Test baseline (re-derived, not trusted from .test-results)

```
$ pytest --collect-only -q          → 54 tests collected
$ pytest -q (containers UP)         → 52 passed, 2 xfailed, 0 skipped, 0 failed
$ pytest tests/integration -v -rxs  → 3 passed (real Mailpit + real GreenMail), 1 xfail
$ pytest -W error::DeprecationWarning -W error::ResourceWarning -W error::RuntimeWarning
                                    → 52 passed, 2 xfailed (log-triage gate clean)
```

The 2 xfails are both the SDK-gated `runtime.execute()` e2e (strict xfail; kailash-py#1182 /
journal 0005). The IMAP + SMTP round-trips PASS against real infra — connector receipts verify
under a real `Ed25519Verifier`.

## Spec → code assertion table (Step 1, re-derived from scratch)

| #   | Spec assertion                                                                     | Verification command                                                                                                                                                                             | Result                     |
| --- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------- |
| 1   | `Connector.__abstractmethods__` = 4 methods + 3 props (7)                          | `Connector.__abstractmethods__` → 7: authenticate/invoke/read/write + auth_verifier/ledger/revocation                                                                                            | PASS                       |
| 2   | `EmailConnector` implements all 7                                                  | `test_connector_satisfies_abc` PASS + ABC instantiates                                                                                                                                           | PASS                       |
| 3   | Unknown-sender → closed-enum `Reject` (fail-closed)                                | `directory.py:1172,1184` returns `REJECT`; SEC-2 probe: unknown invoke → `ConnectorAuthenticationError`, SMTP send NOT fired                                                                     | PASS                       |
| 4   | Disposition enum = `{Accept, Reject, EscalateToHuman}`                             | `UnknownSenderDisposition` enum values match                                                                                                                                                     | PASS                       |
| 5   | `authenticate` runs BEFORE send on `invoke` hot path                               | `connector.py:469` `await self.authenticate(...)` precedes message construction; SEC-2 tripwire confirms                                                                                         | PASS                       |
| 6   | Receipts bind full identity (signer/action_id/observed_at), not bare payload       | `build_action_signing_bytes`/`build_read_signing_bytes`; SEC-3: same payload+diff action_id/signer → diff bytes                                                                                  | PASS                       |
| 7   | Tamper of signer/action_id/payload/observed_at fails verify                        | SEC-3b: genuine→True; tampered signer/payload/wrong observed_at → all False                                                                                                                      | PASS                       |
| 8   | Header injection rejected on every send route                                      | `validate_header_field` at `OutboundMessage.__post_init__`; SEC-1: CRLF/LF/NUL/NEL/LS/PS/VT/leading-ws all rejected on sender/recipient/subject; body CRLF does NOT inject (set_content escapes) | PASS                       |
| 9   | Credentials env-only; no secrets in logs/audit                                     | `_require_env` (no defaults); no `password`/`username` in any `logger`/`ledger.record` call; `.env` gitignored, none tracked                                                                     | PASS                       |
| 10  | SPDX header on every src file                                                      | `head -2` of all 6 src `.py` → Apache-2.0 present                                                                                                                                                | PASS                       |
| 11  | Namespace `delegate_connectors.email` PEP-420 (no `__init__.py` at namespace root) | `find src` — only `email/__init__.py`, no `src/delegate_connectors/__init__.py`                                                                                                                  | PASS                       |
| 12  | `pyproject` floor `kailash>=2.24.0`, packages `["src/delegate_connectors"]`        | `pyproject.toml:18,55-56`                                                                                                                                                                        | PASS                       |
| 13  | No Postgres / no PACT (in-memory audit only)                                       | `compose.py` uses `AuditChainEngine(chain=TrustLineageChain(...))`; no psycopg/postgres/pact import                                                                                              | PASS                       |
| 14  | Test infra: Mailpit (SMTP+REST) + GreenMail (SMTP+IMAP), no IMAP on Mailpit        | `docker-compose.yml` two services; integration tests run green against both                                                                                                                      | PASS                       |
| 15  | `runtime.execute()` call-shape                                                     | **was WRONG in spec (claimed sync); SDK is async coroutine** → spec corrected (journal 0011)                                                                                                     | FIXED                      |
| 16  | Every src module has ≥1 importing test                                             | `grep -rl from delegate_connectors.email.<m> tests/`: connector=5, smtp=8, imap=8, directory=5, compose=3                                                                                        | PASS                       |
| 17  | conformance.md GATED — deferral journaled, not silently dropped                    | `specs/conformance.md` STATUS banner + value-anchor cites journal/0003; cross-repo authz gate documented                                                                                         | PASS (acceptable deferral) |
| 18  | All spec-cited SDK symbols resolve                                                 | importlib check of dispatch/delegate/envelope/types/verifier/conformance — all resolve                                                                                                           | PASS                       |
| 19  | Cross-spec consistency (ports 1025/8025/3025/3143, kailash floor)                  | grep across specs — internally consistent, no contradictions                                                                                                                                     | PASS                       |

## Mechanical sweeps (Round 1 + Round 3)

- Stub/placeholder markers in src: **none** (only hit was the docstring phrase "DOCUMENTED v0 placeholder").
- `eval(`/`exec(`/`os.system`/`shell=True`: **none**.
- Bare/silent except: **none** (the `except Exception: pass` at `imap.py` logout is the documented
  cleanup carve-out per `zero-tolerance.md` Rule 3, `# pragma: no cover`).
- Hardcoded secrets: **none**. `.env`: not tracked, gitignored.
- Correctness edges verified by execution: `_select_rfc822_literal` (empty/framing-only/largest-wins),
  `normalize_address` (display-name strip + symmetric malformed fallback), `invoke` fail-loud KeyError
  on missing required key, `EmailV0Signature` genuinely frozen, RFC-2047 header decode.

## Round log

| Round | Scope                                                                                   | Findings                           |
| ----- | --------------------------------------------------------------------------------------- | ---------------------------------- |
| 1     | spec compliance + adversarial security + correctness + tests + real infra               | 1 (MEDIUM spec sync/async) → fixed |
| 2     | post-fix sibling-spec re-derivation (split-state scan, citation resolution, ABC, suite) | 0 — CLEAN                          |
| 3     | final gate (diff, full suite warnings-as-errors, sweeps, integration re-confirm)        | 0 — CLEAN                          |

Two consecutive clean rounds (2, 3) → convergence.

## Housekeeping done this run

- `specs/runtime-composition.md` — execute() corrected to async (journal 0011).
- `.gitignore` — added `workspaces/**/.journal-skipped.log` (runtime hook bookkeeping, was untracked).
