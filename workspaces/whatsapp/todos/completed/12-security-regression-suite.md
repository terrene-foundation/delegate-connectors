# Todo 12 — Security regression suite (PII redaction · webhook HMAC · Reject gate · receipt-binding)

**Implements:** `specs/test-infrastructure.md` § Tier 1 (regression placement) (+ `02-plans/02-connector-spec.md` § Security — all four binding security properties)
**Type:** Test (regression) · **Capacity:** single shard (~5 invariants)
**Depends:** 02, 05, 06, 07

**Value-anchor:** delivers the brief acceptance criteria "Receipts bind FULL identity … tamper of any field fails verification", "Template-not-approved → typed `Reject` … NOT a silent send failure", and "no credential in any log line or audit payload" — locked as permanent regressions so a future refactor cannot silently reopen any of them.

## Do

- `connectors/whatsapp/tests/regression/` with `@pytest.mark.regression` (NEVER deleted),
  behavioral assertions (call the function, assert raise/return — no source-grep):
  - **PII redaction**: every `SignedActionEnvelope` / `AttestedReadReceipt` canonical-bytes
    payload + every ledger record carries the `wa:`-token, never the raw E.164; a redaction
    failure surfaces the `<unredactable wa identity>` sentinel, never the raw number.
  - **Webhook HMAC boundary**: a payload with a wrong/tampered `X-Hub-Signature-256` is refused
    and never reaches the buffer or the audit path; the compare is constant-time.
  - **Verify-token**: a mismatched `hub.verify_token` yields no `hub.challenge` echo.
  - **Template/window Reject gate**: outside-window free-form → `OutsideServiceWindowError`
    and NO Cloud API call fired; un-approved template → `TemplateNotApprovedError`, no send.
  - **Receipt identity-binding tamper**: mutate signer / action_id / observed_at on a signed
    receipt → `verify_action_envelope` / `verify_read_receipt` fails for each mutated field.

## Invariants (5)

1. Raw phone/`wa_id` is absent from every audit-bytes / ledger / log surface (assert by
   searching the serialized artifacts for the raw digits — must be absent).
2. HMAC-failed inbound never mutates the buffer and never emits an audit event.
3. Each Reject gate blocks the send (transport spy/double records zero calls on Reject).
4. Tampering ANY bound field fails verification (one assertion per field).
5. Tests are behavioral (invoke + assert), placed in `tests/regression/`, marked regression.

## Acceptance

- [ ] `../../.venv/bin/pytest connectors/whatsapp/tests/regression -q` green.
- [ ] Each of the four binding security properties has ≥1 dedicated regression test.
- [ ] No source-grep-only assertions (behavioral per `rules/testing.md`).
