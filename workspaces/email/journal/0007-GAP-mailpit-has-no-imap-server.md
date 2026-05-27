---
type: GAP
date: 2026-05-27
created_at: 2026-05-27T03:35:00Z
author: agent
session_id: email-connector-implement
session_turn: 3
project: email-connector
topic: Mailpit v1.30.0 ships NO IMAP server — spec/test-infrastructure assumption that "Mailpit exposes BOTH SMTP send + IMAP read" is inaccurate; SMTP send is real-infra verifiable via Mailpit's REST API, IMAP fetch cannot execute
phase: implement
tags: [spec-inaccuracy, mailpit, imap, real-infra, test-skip-discipline]
---

# GAP — Mailpit (v1.30.0) provides no IMAP server

## Finding (verified against the running container)

`specs/test-infrastructure.md` § Tier 2/3 states Mailpit is a "single Docker
container; exposes BOTH SMTP send + IMAP read" and the topology line claims
"IMAP :1143". The pulled `axllent/mailpit:latest` resolves to **v1.30.0**,
whose startup log shows ONLY `[smtpd]` + `[http]` — there is no `[imap]`
listener:

```
[smtpd] starting on [::]:1025 (no encryption)
[http]  starting on [::]:8025
```

The `MP_IMAP_*` env vars are silently ignored; `nc localhost 1143` returns no
banner; `aioimaplib.wait_hello_from_server()` times out. **This Mailpit release
has no IMAP server.** (MailHog also lacks IMAP — the spec already noted that;
the spec's claim that Mailpit fills the gap is what's inaccurate.)

## What IS real-infra verifiable

- **SMTP send** works against real Mailpit. A message sent through the
  connector's `SmtpTransport`/`write` path arrives in Mailpit; Mailpit's REST
  API (`GET :8025/api/v1/messages`) confirms it byte-for-byte (subject, From,
  To, Message-ID). This is genuine no-mock-at-the-boundary integration — the
  send transits a real SMTP server.
- **Receipt signing + verification** (`read`/`write` → non-empty
  `SignedActionEnvelope` / `AttestedReadReceipt` verifying under the real
  `Ed25519Verifier`) is fully exercised in Tier-1 against the real shipped
  crypto stack — no infra needed for that half.

## What cannot execute (and is NOT faked)

- The connector's **IMAP fetch** path (`ImapTransport.fetch` against a live
  IMAP server) has no server to connect to. Per `test-skip-discipline` this is
  the ACCEPTABLE-skip class ("cannot execute — no IMAP server available"), NOT
  a masked failure. The IMAP integration test is `pytest.mark.skipif`-gated on
  IMAP-server reachability with a clear reason; the IMAP PARSING logic is
  covered offline in Tier-1 (`parse_rfc822`, literal selection, RFC-2047).

## Disposition

- SMTP round-trip integration test verifies the send via Mailpit's REST API
  (real infra, no mock).
- IMAP fetch integration test skips with reason "no IMAP server (Mailpit
  v1.30.0 ships none)" until a real IMAP server is provisioned.
- Spec follow-up (in-repo, no cross-repo): `specs/test-infrastructure.md`
  should either pin a Mailpit version that ships IMAP (if one exists) or swap
  the inbound-read infra to a JVM GreenMail container (real IMAP), OR scope the
  inbound round-trip to the REST-API read. Recommended: GreenMail for a real
  IMAP server when the inbound round-trip must run end-to-end; until then the
  SMTP send + REST confirmation + offline IMAP-parsing coverage is the
  buildable real-infra surface.

## For Discussion

1. The spec asserted Mailpit "exposes BOTH SMTP + IMAP" — what should `/analyze`
   have done to catch this before `/todos` (e.g. `docker run` the exact image
   and grep the startup log for an `[imap]` line)?
2. Counterfactual: if GreenMail (JVM, real IMAP) had been the chosen container
   from the start, the inbound round-trip would run e2e but the container is
   heavier and slower. Is a real IMAP server worth the weight for v0, or is
   SMTP-send + REST-confirm + offline-parse sufficient real-infra coverage?
3. Mailpit's REST API can read received messages — but the CONNECTOR reads via
   IMAP, not REST. Would adding a REST-backed inbound transport (parallel to
   the IMAP one) be a useful v0 test affordance, or does it dilute the
   "connector uses IMAP" contract?
