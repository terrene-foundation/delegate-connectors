# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Slack security regression suite (Tier-2, behavioral).

Permanent (NEVER-deleted) behavioral regressions locking the binding security
properties of the Slack connector:

1. Receipt identity-binding — receipts bind FULL identity (signer/attester +
   action_id/read_id + observed_at) into the signed bytes; two identical-payload
   writes have distinct signatures; tampering any bound field fails verification.
2. Authenticate-first Reject gate — ``invoke`` authenticates FIRST; an unknown
   principal raises ``ConnectorAuthenticationError`` (fail-closed Reject) and ZERO
   ``chat.postMessage`` fires.
3. Outbound construction-boundary validation — a malformed channel id raises at
   the ``OutboundSlackMessage`` boundary BEFORE any post; user text is
   mrkdwn-escaped (the shipped behavior; no oversized/control-char rejection is
   invented).

Every test is ``@pytest.mark.regression`` and behavioral (invoke the function,
assert raise/return) — NEVER a source-grep assertion.
"""
