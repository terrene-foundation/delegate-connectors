# Todo 09 — Regression tests (receipt binding, invoke-authenticates-first, outbound validation)

**Implements:** `specs/connector-contract.md` § The interface
(+ `02-plans/02-connector-spec.md` § Unknown-sender disposition + § Transport + § Security)
**Type:** Test (regression) · **Capacity:** single shard (~3 invariants)
**Depends:** 04, 05

## Do

`connectors/telegram/tests/regression/` — behavioral regression tests (call the
function; assert raise/return — NOT source-grep), each `@pytest.mark.regression`,
NEVER deleted:

- `test_receipt_identity_binding.py` — receipts bind FULL identity into the signed
  bytes: two identical-payload `write`s have distinct `action_id` + distinct
  `canonical_bytes` + distinct signatures; an action envelope verifies with bound
  identity; tampering `signer_delegate_id` fails `verify_action_envelope`; a read
  receipt binds the attester and tampering `attester_delegate_id` fails
  `verify_read_receipt`.
- `test_invoke_authenticates.py` — `invoke` authenticates FIRST: an unknown principal
  raises `ConnectorAuthenticationError` (match `Reject`) and ZERO Bot API send fires
  (record-and-assert the send was never called); a known principal authenticates and
  the send proceeds once (`external_side_effect=True`).
- `test_outbound_validation.py` — the outbound `chat_id`/`text` construction boundary:
  a `text` carrying CR/LF/NUL/control chars or exceeding 4096 UTF-16 units, or a
  malformed `chat_id`, raises the typed validation error at `OutboundMessage`
  construction BEFORE any Bot API call — and on the `invoke` hot path the typed error
  raises with ZERO send fired.

## Invariants (3)

1. Identity-binding tamper-fail holds for BOTH `write` (signer) and `read` (attester).
2. `invoke` on an unknown sender raises and fires ZERO Bot API send.
3. Outbound validation rejects at the construction boundary on EVERY route (direct
   construction AND the `invoke` hot path), firing ZERO send on rejection.

## Acceptance

- [ ] `../../.venv/bin/python -m pytest connectors/telegram/tests/regression -q` green.
- [ ] Each test calls the real function and asserts raise/return (behavioral, not
      source-grep).
- [ ] The unknown-sender path and the outbound-validation path each assert ZERO send.
