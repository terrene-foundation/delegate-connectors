# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Security regression suite for the WhatsApp connector.

Permanent (NEVER-deleted) behavioral regressions locking the four binding
security properties of the WhatsApp connector:

1. PII redaction — every audit-bytes / ledger surface carries the ``wa:``-token,
   never the raw E.164; a redaction failure surfaces the ``<unredactable wa
   identity>`` sentinel.
2. Webhook HMAC boundary — a wrong/tampered ``X-Hub-Signature-256`` is refused,
   never buffered, never audited; the compare is constant-time; a mismatched
   ``hub.verify_token`` echoes no ``hub.challenge``.
3. Template / service-window Reject gate — outside-window free-form and
   un-approved template both raise a typed Reject BEFORE any Cloud API call
   (zero transport calls on Reject).
4. Receipt identity-binding tamper — mutating signer / action_id / observed_at
   on a signed receipt fails ``verify_action_envelope`` / ``verify_read_receipt``.

Every test is marked ``@pytest.mark.regression`` and is behavioral (invoke the
function, assert raise/return) — never a source-grep assertion.
"""
