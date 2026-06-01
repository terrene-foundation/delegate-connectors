# P0-07 — Build the host-side credential broker (host owns from_env(); mints scoped credential sets; injects BoundTransport; covers all 4 whatsapp secrets incl. runtime PII-HMAC)

> **Milestone:** P0 — Decoupling foundation  ·  **Load-bearing:** YES  ·  **Wire todo:** no  ·  **Est:** ~200 LOC
> **Depends on:** P0-06
> **Implements:** architecture §3.5 layer 2; architecture §7 Phase 0; specs bound_transport_requirements; value-prioritization MUST-1

## What (≤3 sentences)

Build the credential broker: the HOST owns from_env() and constructs the credential-bearing transport, then injects an opaque BoundTransport (from P0-06) into the connector. The connector declares requires_credentials and receives the handle, never the raw secret. The broker must support multiple scoped credential classes per delegation: email needs 2 (SMTP+IMAP); whatsapp needs FOUR distinct secrets across THREE files — WHATSAPP_ACCESS_TOKEN (cloud_api.py:128/159-161), WHATSAPP_APP_SECRET + WHATSAPP_WEBHOOK_VERIFY_TOKEN (webhook.py:69/88-89, TWO secrets via one _require_env), WHATSAPP_PII_HMAC_KEY (redaction.py:114/144 startup gate AND redaction.py:154 _hmac_key per-message RUNTIME read). The broker must feed the PII-HMAC key into BOTH the startup gate AND the runtime redact_phone() path (security MEDIUM / completeness MEDIUM findings).

## Deliverable

A new `delegate_connectors_host/credential_broker.py`: a broker that owns from_env() per credential class, builds the underlying transport, returns a BoundTransport keyed on the connector's declared requires_credentials set, AND supplies the PII-HMAC key to both the whatsapp startup gate and the per-message runtime redaction path.

## Files touched

- delegate_connectors_host/credential_broker.py (new — host-side broker)
- connectors/whatsapp/src/delegate_connectors/whatsapp/redaction.py:144 (PII HMAC startup-gate read — broker reproduces this fail-closed gate)
- connectors/whatsapp/src/delegate_connectors/whatsapp/redaction.py:154 (_hmac_key per-message runtime read — broker must inject the key here too, NOT leave an os.environ read; security MEDIUM finding)

## Invariants (MUST hold)

- the HOST owns from_env(); the connector never calls os.environ (credential-blindness)
- broker mints scoped credential sets per declared requires_credentials class — email->{smtp,imap}; whatsapp->{access_token, app_secret, webhook_verify_token, pii_hmac_key} (FOUR secrets, re-derived from source per completeness MEDIUM finding — app_secret and webhook_verify_token are SEPARATE secrets serving HMAC-verify vs challenge-response)
- broker injects a BoundTransport, never the raw config/secret
- the PII-HMAC key reaches BOTH the whatsapp startup gate (redaction.py:144 RedactionConfig.from_env) AND the per-message runtime path (redaction.py:154 _hmac_key) via broker injection — so redact_phone produces a REAL HMAC, never the redacted-failure sentinel from a missing-key fallback (security MEDIUM / completeness MEDIUM — the fake-redaction failure mode of zero-tolerance Rule 2)
- fail-closed: a missing required credential refuses to compose (reproduce whatsapp's hard PII-HMAC startup gate at redaction.py:144 / connector.py:336)
- a connector declaring a credential class it was not granted cannot obtain that class's transport

## Value anchor

Architecture §3.5 layer 2 + §7 Phase 0: "the host owns from_env() and injects an opaque BoundTransport". HIGHEST user-value (value-prioritization MUST-1): converts the marketed narrow-subset claim into the real credential-blind wedge. Brief success criterion: "it cannot see credentials it wasn't granted".

## Acceptance criteria

- [ ] broker owns from_env() for every credential class; connectors no longer read os.environ
- [ ] broker injects BoundTransport handles and mints per-class scoped credential sets (email 2; whatsapp 4 secrets across 3 classes)
- [ ] whatsapp PII-HMAC key reaches both the startup gate AND the runtime redact path (no os.environ read survives in redaction.py); redact_phone yields a real HMAC, not the sentinel
- [ ] missing-credential composition fails closed (whatsapp PII-HMAC startup gate preserved)

## Test plan

Unit: broker.mint('smtp') reads EMAIL_SMTP_* host-side and returns a BoundTransport whose send() works but whose .config is absent; broker for an UNGRANTED class refuses; missing required credential -> fail-closed refusal (whatsapp PII-HMAC gate reproduced); email mints TWO scoped sets; whatsapp mints FOUR secrets across three classes and feeds the PII-HMAC key to BOTH the startup gate and the runtime redact path; assert redact_phone under broker composition yields a real HMAC token (wa:<8hex>), NOT the sentinel. BUILD half of the ungranted-secret invariant TEST in P0-13.
