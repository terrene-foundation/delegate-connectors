# Todo 15 — Fail loud at startup on missing `WHATSAPP_PII_HMAC_KEY`

**Implements:** workspaces/whatsapp/02-plans/02-connector-spec.md § Security (PII redaction)
**Type:** Build (security hardening) · **Capacity:** single shard (~50 LOC, 2 invariants)
**Depends:** 02 (redaction-helper, already complete)
**Origin:** Wave-1 security review (L2, 2026-05-28). Symmetric with the existing `_require_env` guards on `WHATSAPP_APP_SECRET` + `WHATSAPP_WEBHOOK_VERIFY_TOKEN` — the PII key has equal load-bearing status and should refuse at startup, not silently emit the sentinel per message.

## Do

- `connectors/whatsapp/src/delegate_connectors/whatsapp/redaction.py` — add a
  `RedactionConfig` (dataclass) + `RedactionConfig.from_env()` that calls a
  shared `_require_env("WHATSAPP_PII_HMAC_KEY")` (mirror the same helper shape
  webhook.py uses) and raises a typed `RedactionConfigError` on missing/empty.
- `redact_phone()` keeps its current contract (returns the sentinel if the key
  is somehow unset at call time — runtime robustness for a single rotation
  glitch), BUT the `RedactionConfig.from_env()` factory is the load-bearing
  startup gate that the connector's `__init__` (todo 07) MUST invoke.
- Document the dual contract clearly in the redaction module docstring: startup
  raises loud; per-message redaction stays fail-soft.

## Invariants (2)

1. `RedactionConfig.from_env()` raises `RedactionConfigError` when `WHATSAPP_PII_HMAC_KEY` is unset or empty (loud at startup).
2. `redact_phone()` keeps emitting the sentinel `<unredactable wa identity>` on per-message redaction failure (runtime robustness preserved).

## Acceptance

- [ ] Unit test: `RedactionConfig.from_env()` raises with `WHATSAPP_PII_HMAC_KEY` unset.
- [ ] Unit test: `RedactionConfig.from_env()` raises with `WHATSAPP_PII_HMAC_KEY = ""`.
- [ ] Unit test: `RedactionConfig.from_env()` succeeds with a valid key set.
- [ ] Unit test: `redact_phone()` still returns the sentinel when the env-var is unset at call time (runtime contract preserved).
- [ ] When todo 07 (`WhatsAppConnector.__init__`) lands, it calls `RedactionConfig.from_env()` so an installation with no PII key refuses startup.
