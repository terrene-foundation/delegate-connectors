# Spec — Test Infrastructure

3-tier testing (`rules/testing.md`). Tier 2/3 use REAL infrastructure — no mocks at
the boundary. **No Postgres, no PACT.** Two mail containers: Mailpit for the
outbound SMTP-arrival assertion (real SMTP + a REST search API) and GreenMail
for the inbound IMAP round-trip (real SMTP **and** real IMAP — Mailpit v1.30.0
ships no IMAP server).

## Tier 1 (unit)

Pure-Python, no I/O. Connector logic with the external thunk stubbed at the
SDK-boundary only (the thunk itself, not the connector contract). Principal
resolution, envelope tightening, payload shaping, unknown-sender → `Reject`.

## Tier 2/3 (integration / e2e) — real infra

| Dependency       | Provision                                                            | Why                                                                                                                                  |
| ---------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| SMTP send + REST | **Mailpit** (SMTP :1025, REST/UI :8025)                              | Outbound send + REST arrival assertion. Mailpit v1.30.0 ships **no** IMAP server (journal 0007), so it cannot back inbound fetch.    |
| SMTP + IMAP      | **GreenMail** (`greenmail/standalone`; real SMTP :3025 + IMAP :3143) | Inbound round-trip: send via GreenMail SMTP, fetch back via GreenMail IMAP through the connector's `read` path. One JVM, both ports. |
| Audit chain      | **In-memory** `AuditChainEngine(chain)`                              | Shipped runtime audit is in-memory. NO Postgres container.                                                                           |
| Trust verify     | `Ed25519Verifier(PrincipalDirectory(...))`                           | Real signature verification (NOT `NullVerifier`).                                                                                    |

No PACT engine container. No Postgres container. (#1035's "real PACT + real
Postgres" is over-specified vs the shipped runtime — see `conformance.md` and
`workspaces/email/01-analysis/00-synthesis.md` BLOCKER-2.)

## Topology

- `docker-compose.yml`: two services — `mailpit` (SMTP :1025, REST/UI :8025) and
  `greenmail` (`greenmail/standalone`; SMTP :3025, IMAP :3143, bound 0.0.0.0,
  `auth.disabled`).
- Reachability gates in `tests/integration/_mailpit.py`: `requires_mailpit_smtp`
  (Mailpit SMTP + REST) and `requires_greenmail` (GreenMail SMTP + IMAP). Tests
  skip with a "cannot execute" reason when the container is not reachable.
- Inbound round-trip: send via GreenMail SMTP to `bob@example.com` → the IMAP
  transport logs in AS `bob` (mailbox auto-created on first login under
  `auth.disabled`) → fetch back through the connector's `read` path → assert a
  verifiable, identity-bound `AttestedReadReceipt`.
- e2e: compose a `DelegateRuntime` with the `EmailConnector` → `runtime.execute(...)`
  triggers an SMTP send to Mailpit → assert `RuntimeExecutionResult` carries a
  verifiable `SignedActionEnvelope`. (The end-to-end `runtime.execute()` is xfail
  gated on an SDK audit-emit fix — journal 0005.)

## Receipt agreement (cross-impl)

`assert_receipts_agree(result_a.to_dict(), result_b.to_dict())` — deep-compares
ordered audit chains, timestamps excluded. v0 demonstrates intra-impl determinism
(two runs agree). Cross-LANGUAGE agreement (py chain verifies under rs verifier)
is deferred — it requires the rs verifier, out of this repo's scope.
