# Spec — Email Connector (v0)

The first connector. Implements `Connector` (see `connector-contract.md`) for email.

## Responsibilities (mapped to the ABC)

| ABC member                               | Email behavior                                                                                                                                                                    |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authenticate(identity, envelope)`       | Resolve the sender/recipient email address in `identity` to a `Principal` against a `PrincipalDirectory`. Unknown sender → disposition per § Unknown-sender below.                |
| `write(action, *, identity, envelope)`   | `action` is a thunk wrapping an **SMTP send**. Execute under audit; return `SignedActionEnvelope`. The send is the auditable external side-effect.                                |
| `read(query, *, identity, envelope)`     | `query` is a thunk wrapping an **IMAP fetch** (poll/fetch messages). Execute under audit; return `(messages, AttestedReadReceipt)`.                                               |
| `invoke(payload, *, identity, envelope)` | Single-method entry: dispatch to send (write) based on `payload` shape; return `ConnectorInvocationResult(payload, audit_events, tenant_id_observed, external_side_effect=True)`. |
| `auth_verifier`                          | `Ed25519Verifier(directory)` (shipped concrete).                                                                                                                                  |
| `ledger`                                 | Spine-shipped `KnowledgeLedger` concrete (framework-first; no custom).                                                                                                            |
| `revocation`                             | Spine-shipped `RevocationChannel` concrete.                                                                                                                                       |

## Transport

- **SMTP** (outbound): `smtplib`/`aiosmtplib` to a configured host. Credentials from
  `.env` (`EMAIL_SMTP_HOST/PORT/USER/PASSWORD`) — never hardcoded (`security.md`).
- **IMAP** (inbound): `imaplib`/`aioimaplib` to a configured host. Credentials from
  `.env` (`EMAIL_IMAP_HOST/PORT/USER/PASSWORD`).

## Principal resolution

v0: exact-match lookup of the normalized `From:`/recipient address against
`PrincipalDirectory`. (Alias / domain-rule resolution deferred — out of v0 scope.)

## Unknown-sender disposition

`expected` outcomes are the closed enum `{Accept, Reject, EscalateToHuman}`
(conformance). An unknown sender MUST resolve to **`Reject`** in v0 (fail-closed;
not `Accept`). `EscalateToHuman` reserved for a later policy shard.

## v0 out-of-scope

OAuth2/Gmail/M365 provider auth; HTML/MIME rendering; attachments beyond
passthrough; calendar/S-MIME; threading/References chain integrity; dispatch /
classification / supervisor (spine concerns); the other 3 connectors.

## Security

- All credentials via `.env`; root `.env` git-ignored; `.env.example` template only.
- No secrets in logs or audit payloads.
- Input validation on inbound message fields before they enter the audit path.
