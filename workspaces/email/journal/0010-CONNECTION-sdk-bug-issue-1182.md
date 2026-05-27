---
type: CONNECTION
date: 2026-05-27
created_at: 2026-05-27T00:00:00Z
author: co-authored
session_id: email-connector-run
session_turn: 15
project: email
topic: links the runtime e2e xfail to upstream tracker kailash-py#1182
phase: redteam
tags: [upstream-issue, xfail, sdk-bug, traceability]
---

# CONNECTION — runtime e2e xfail ↔ kailash-py#1182

The `runtime.execute()` e2e tests (`tests/integration/test_e2e.py`,
`tests/integration/test_compose.py`) are STRICT xfail gated on the SDK
audit-signature defect (journal 0005 / 0009). That defect now has an upstream
tracker:

**https://github.com/terrene-foundation/kailash-py/issues/1182** (filed 2026-05-27,
user-authorized — journal 0009).

## When #1182 closes (action for the future session)

1. Re-run the connector e2e under the fixed kailash version — the strict xfail
   should flip to XPASS, forcing marker removal (`pytest` fails XPASS by design).
2. Remove the `xfail(strict=True)` markers citing journal 0005.
3. Revisit issue #1035's "Delegate runs end-to-end" acceptance — it becomes
   satisfiable once #1182 lands.

## Related

- journal 0005 (GAP — the defect discovery)
- journal 0009 (DECISION — cross-repo filing authorization)
- The deferred conformance shard (journal 0003) is independent of #1182.

## For Discussion

1. Should the connector pin a `kailash` floor that EXCLUDES the broken range once
   #1182's fix ships, or rely on the xfail→xpass flip to signal the upgrade?
2. Counterfactual: if #1182 is fixed by moving the sign-site AFTER entry
   construction, do the connector's OWN receipt-signing helpers (which sign
   `{payload, signer, action_id, observed_at}`) need to change for parity?
