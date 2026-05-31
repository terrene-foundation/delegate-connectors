# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-3 e2e: compose a DelegateRuntime and drive it against real Mailpit.

The end-to-end ``runtime.execute()`` assertion (a COMPLETED run carrying a
verifiable SignedActionEnvelope in the audit chain) is gated on
``@requires_mailpit_smtp`` — it SKIPs when Mailpit is not reachable (cannot
execute) and passes when it is. The SDK bug (kailash-py#1182) was fixed at
<= 2.28.1 (workspaces/whatsapp/journal/0008); the strict xfail marker is
removed and execute() now completes.

Intra-impl receipt determinism is asserted separately via ``assert_receipts_agree``
— the per-run-unique fields (``run_id``, ``at``, ``dispatch_id``,
``audit_head_hash``, ``audit_chain_entries``) are excluded from the comparison.
"""

from __future__ import annotations

import uuid

import pytest

from kailash.delegate import assert_receipts_agree

from delegate_connectors.email.compose import build_email_runtime
from delegate_connectors.email.imap import ImapConfig, ImapTransport
from delegate_connectors.email.smtp import OutboundMessage, SmtpConfig, SmtpTransport

from _mailpit import (
    IMAP_PORT,
    MAILPIT_HOST,
    SMTP_PORT,
    requires_mailpit_smtp,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _composed():
    smtp = SmtpTransport(SmtpConfig(host=MAILPIT_HOST, port=SMTP_PORT))
    imap = ImapTransport(ImapConfig(host=MAILPIT_HOST, port=IMAP_PORT))
    return build_email_runtime(smtp=smtp, imap=imap, sender_email="alice@example.com")


@requires_mailpit_smtp
async def test_runtime_execute_e2e_against_mailpit_completes():
    """End-to-end run completes against real Mailpit on kailash >= 2.28.0.

    Was strict-xfailed on kailash-py#1182 (audit-emit signed payload bytes while
    AuditChainEngine verified full entry bytes; execute() failed at the first
    phase transition). Fixed at <= 2.28.1 (workspaces/whatsapp/journal/0008);
    the marker is removed and the run now completes carrying a dispatch result.
    """
    composed = _composed()
    result = await composed.runtime.execute(
        {
            "sender": "alice@example.com",
            "to": "bob@example.com",
            "subject": "e2e-" + uuid.uuid4().hex[:8],
            "body": "end to end",
        }
    )
    assert result.taod_state.phase == "completed"
    assert result.dispatch_result is not None


@requires_mailpit_smtp
async def test_runtime_execute_is_deterministic_across_two_runs():
    """Two fresh runtimes given identical input produce agreeing receipts.

    ``assert_receipts_agree`` deep-compares the receipt tree minus the per-run
    identity fields: ``run_id`` + the per-transition ``at`` timestamp, plus the
    three fields that are per-run-by-design now that execute() completes —
    ``dispatch_id`` (a fresh UUID per dispatch), ``audit_head_hash`` and
    ``audit_chain_entries`` (SHA-256 hashes that incorporate ``dispatch_id`` and
    per-run audit state). Audit-chain *integrity* (round-trip + head-hash
    re-validation) is a distinct property covered by the conformance vector
    DV-9-001; this test asserts the *outcome* is deterministic (same phase,
    transition shape, dispatch result) for identical input.
    """
    payload = {
        "sender": "alice@example.com",
        "to": "bob@example.com",
        "subject": "determinism-fixed-subject",
        "body": "identical body",
    }
    r1 = await _composed().runtime.execute(dict(payload))
    r2 = await _composed().runtime.execute(dict(payload))

    assert_receipts_agree(
        r1.to_dict(),
        r2.to_dict(),
        exclude_fields=frozenset(
            {
                "run_id",
                "at",
                "dispatch_id",
                "audit_head_hash",
                "audit_chain_entries",
                # message_id is the SMTP Message-ID header — per-RFC-5322
                # generated fresh per OutboundMessage construction, so it is
                # per-run-unique by design (same category as dispatch_id).
                "message_id",
            }
        ),
    )
