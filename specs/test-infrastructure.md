# Spec — Test Infrastructure

3-tier testing (`rules/testing.md`). Tier 2/3 use REAL infrastructure — no mocks at
the boundary. Reality is lighter than the brief feared: **one container, no
Postgres, no PACT**.

## Tier 1 (unit)

Pure-Python, no I/O. Connector logic with the external thunk stubbed at the
SDK-boundary only (the thunk itself, not the connector contract). Principal
resolution, envelope tightening, payload shaping, unknown-sender → `Reject`.

## Tier 2/3 (integration / e2e) — real infra

| Dependency         | Provision                                                                 | Why                                                                          |
| ------------------ | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| SMTP + IMAP server | **Mailpit** (single Docker container; exposes BOTH SMTP send + IMAP read) | Real send/fetch round-trip. MailHog lacks IMAP; GreenMail is a JVM fallback. |
| Audit chain        | **In-memory** `AuditChainEngine(chain)`                                   | Shipped runtime audit is in-memory. NO Postgres container.                   |
| Trust verify       | `Ed25519Verifier(PrincipalDirectory(...))`                                | Real signature verification (NOT `NullVerifier`).                            |

No PACT engine container. No Postgres container. (#1035's "real PACT + real
Postgres" is over-specified vs the shipped runtime — see `conformance.md` and
`workspaces/email/01-analysis/00-synthesis.md` BLOCKER-2.)

## Topology

- `docker-compose.yml` (new): one `mailpit` service (SMTP :1025, IMAP :1143, UI :8025).
- `conftest.py` (new at connector package root): session-scoped fixture that
  starts/waits-for Mailpit, yields SMTP/IMAP coordinates, tears down.
- e2e: compose a `DelegateRuntime` with the `EmailConnector` → `runtime.execute(...)`
  triggers an SMTP send to Mailpit → assert the message arrives via IMAP fetch →
  assert `RuntimeExecutionResult` carries a verifiable `SignedActionEnvelope`.

## Receipt agreement (cross-impl)

`assert_receipts_agree(result_a.to_dict(), result_b.to_dict())` — deep-compares
ordered audit chains, timestamps excluded. v0 demonstrates intra-impl determinism
(two runs agree). Cross-LANGUAGE agreement (py chain verifies under rs verifier)
is deferred — it requires the rs verifier, out of this repo's scope.
