# Todo 02 — Phone-number PII redaction helper (salted-HMAC)

**Implements:** `specs/connector-contract.md` § Type catalog (audit receipts carry redacted bytes) (+ `02-plans/02-connector-spec.md` § Security — "Phone-number PII redaction (binding)")
**Type:** Build (LOAD-BEARING SECURITY) · **Capacity:** single shard (~90 LOC, 4 invariants)
**Depends:** 01

**Value-anchor:** delivers the brief acceptance criterion "no credential in any log line or audit payload" and the privacy half of "Inbound message read … signed `AttestedReadReceipt`" — phone numbers are PII and MUST never appear raw in audit/ledger/logs.

## Do

- `src/delegate_connectors/whatsapp/redaction.py`:
  - `redact_phone(raw: str) -> str` — salted-HMAC-SHA256 of the normalized number,
    keyed by `WHATSAPP_PII_HMAC_KEY` (env), rendered as the stable token `wa:<first-8-hex>`.
  - A grep-able failure sentinel `<unredactable wa identity>` returned on any redaction
    failure (missing key, un-normalizable input) — NEVER the raw number, NEVER an exception
    that leaks the raw value in its message.
  - A shared E.164 normalization routine reused by the directory (todo 04) and the
    cloud-api send (todo 03), so the redaction token is stable across send + receive.

## Invariants (4)

1. Same raw number → same token within a process (deterministic, key-stable).
2. The sentinel is distinct from any success token (so audit scans can detect failures).
3. `WHATSAPP_PII_HMAC_KEY` read only from env; absent key → sentinel, not a raw fallback.
4. The raw number never appears in a return value, log line, or exception message from this module.

## Acceptance

- [ ] Unit (Tier-1): `redact_phone("+14155550100")` returns a `wa:`-prefixed 8-hex token;
      two calls agree; the raw digits are absent from the output (`assert "14155550100" not in out`).
- [ ] Unit: missing `WHATSAPP_PII_HMAC_KEY` → returns the sentinel, raw absent from output and
      from the (caught) error path.
- [ ] `grep` of the module source is clean for any hardcoded key literal.

## Verification

Completed in /implement Wave 1 (2026-05-28).

- `src/delegate_connectors/whatsapp/redaction.py` created:
  `redact_phone(raw) -> "wa:<first-8-hex>"` salted-HMAC-SHA256 keyed by
  `WHATSAPP_PII_HMAC_KEY` (env-only); shared `normalize_e164` reused by the
  directory (todo 04) and webhook (todo 05); failure sentinel
  `REDACTION_SENTINEL = "<unredactable wa identity>"`.
- Tier-1 tests `tests/unit/test_redaction.py` — 9 tests, all green:
  - `wa:`-prefixed 8-hex token returned; two calls agree (deterministic,
    key-stable); surface-format variants of one number → one token.
  - Different key → different token.
  - Missing `WHATSAPP_PII_HMAC_KEY` → sentinel (raw absent from output).
  - Un-normalizable input → sentinel (raw absent from output).
  - `normalize_e164("not-a-number")` raises `ValueError` whose message does NOT
    echo the raw input.
  - Sentinel is distinct from any `wa:` success token.
- All 4 invariants hold: deterministic/key-stable (1); sentinel distinct (2);
  env-only key, no raw fallback (3); raw number never in a return value / log /
  exception message (4). The HMAC is keyed via `os.environ` only — module source
  carries no hardcoded key literal.
