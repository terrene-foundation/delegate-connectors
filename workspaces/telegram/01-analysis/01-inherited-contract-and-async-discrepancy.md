# 01 — Inherited Contract + the execute() async discrepancy

The Telegram connector is the second pattern-lift after email. The SHARED SDK
reality (the `Connector` ABC, the runtime composition, the audit/trust spine, the
conformance harness, the monorepo layout) was already verified for email against
the shipped wheel and is INHERITED here — not re-litigated. This doc records (a)
the inherited contract as it applies to Telegram, and (b) one discrepancy found
while re-introspecting the wheel that the channel specs MUST reflect.

## Inherited from email v0 (re-confirmed against kailash 2.26.2)

Introspected via the repo-local interpreter (`.venv/bin/python`, kailash 2.26.2):

- `Connector.__abstractmethods__` = `{authenticate, invoke, read, write,
auth_verifier, ledger, revocation}` — 4 methods + 3 properties. Subclass the
  ABC DIRECTLY (ADR-1 inherited); `LegacyInvokeConnector` is REJECTED (empty
  unverifiable receipts; trust properties raise).
- Signatures (verbatim from the wheel):
  - `authenticate(self, identity: DelegateIdentity, envelope: DelegateConstraintEnvelope) -> Principal`
  - `invoke(self, input_payload: dict[str, Any], *, identity, envelope) -> ConnectorInvocationResult`
  - `read(self, query: Callable[[], Awaitable[T_Read]], *, identity, envelope) -> tuple[T_Read, AttestedReadReceipt]`
  - `write(self, action: Callable[[], Awaitable[Any]], *, identity, envelope) -> SignedActionEnvelope`
- `read`/`write` take a **zero-arg async thunk** run UNDER AUDIT (ADR-1).
- Runtime = `DelegateRuntime` + `DispatchSurface` constructed directly (ADR-2);
  `Delegate` is an alias of `DelegateRuntime`; `Delegate.compose(...)` /
  `delegate.run()` / `pact_engine=` DO NOT EXIST.
- Audit = in-memory `AuditChainEngine(TrustLineageChain)`; trust =
  `Ed25519Verifier(PrincipalDirectory)`. NO Postgres, NO PACT (ADR-3).

These are settled. The Telegram connector reuses the email connector's signing
helpers contract (`build_action_signing_bytes` / `build_read_signing_bytes` bind
FULL identity: signer + action*id/read_id + observed_at), the in-memory
`InMemoryKnowledgeLedger` / `NeverRevokedChannel` Protocol adapters, and the
`build*\*\_runtime` composition shape — these are channel-agnostic.

## DISCREPANCY found this session: execute() is async, not sync

Re-introspecting the wheel to confirm the runtime contract for the Telegram spec:

```
$ .venv/bin/python -c "import inspect; from kailash.delegate import DelegateRuntime; \
                       print(inspect.iscoroutinefunction(DelegateRuntime.execute))"
True
```

`DelegateRuntime.execute(self, input_payload: dict[str, Any]) -> RuntimeExecutionResult`
is a **coroutine** — callers MUST `await` it.

Two repo artifacts disagree with each other on this point:

| Source                                            | Claim                        | Verdict vs shipped wheel |
| ------------------------------------------------- | ---------------------------- | ------------------------ |
| `specs/runtime-composition.md:38` (PR #5)         | async                        | CORRECT                  |
| `workspaces/email/01-analysis/00-synthesis.md:30` | "sync, not run(), not async" | **STALE / WRONG**        |

The shared `specs/runtime-composition.md` is CORRECT (it was corrected in PR #5;
the email workspace's own `journal/0011-GAP-*` records the fix). The email
SYNTHESIS doc was not back-patched and still reads "sync". The Telegram spec
(`specs/telegram-connector.md`) and plan MUST cite the async coroutine contract,
matching `specs/runtime-composition.md`, NOT the stale email synthesis line. This
is a cross-doc staleness note, NOT a blocker — the Telegram connector inherits the
async-await call shape that email's CODE already uses correctly.

## What this means for the Telegram shards

The Telegram connector's `read`/`write`/`invoke`/`authenticate` are all `async def`
(matching the ABC), and the composed runtime's `execute()` is awaited. Nothing
Telegram-specific changes the call shape — the transport underneath the thunks is
HTTP (Bot API) instead of SMTP/IMAP, but the audited-thunk contract is identical.

## For Discussion

1. The email synthesis line 30 says "sync" while `specs/runtime-composition.md`
   says "async" — both were authored in the same email session. Which surface is
   the one a future Telegram-connector author would actually read first, and does
   that change whether the stale synthesis line is harmless or a lookaway trap?
2. If `DelegateRuntime.execute` had genuinely been sync, would the Telegram
   transport's HTTP calls (inherently async via the chosen client) have forced an
   `asyncio.run()` bridge inside the thunk — and would that have violated
   `rules/patterns.md` § "Paired Public Surface — Consistent Async-ness"?
3. The async contract is inherited, not Telegram-specific. Is there ANY Telegram
   transport choice (long-poll vs webhook) that would surface a DIFFERENT runtime
   call shape, or is the runtime boundary fully channel-agnostic?
