# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Phone-number PII redaction (binding security floor).

Phone numbers and ``wa_id``s are PII. Every audit payload (the canonical bytes
of a ``SignedActionEnvelope`` / ``AttestedReadReceipt``), every ledger record,
and every log line MUST carry a stable salted-HMAC-SHA256 token of the form
``wa:<first-8-hex>`` — NEVER the raw E.164. The raw number lives only in the
transient outbound HTTPS body to Meta and is dropped after the send.

:func:`redact_phone` is deterministic + key-stable within a process: the same
raw number yields the same token, keyed by ``WHATSAPP_PII_HMAC_KEY`` (env-only).
On ANY redaction failure — missing key, un-normalizable input — it returns the
grep-able sentinel :data:`REDACTION_SENTINEL` (``<unredactable wa identity>``),
NEVER the raw number and NEVER an exception whose message leaks the raw value.

:func:`normalize_e164` is the shared normalization routine reused by the
principal directory (todo 04) and the future Cloud API send (todo 03), so the
redaction token is stable across both the send and receive surfaces.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

__all__ = [
    "redact_phone",
    "normalize_e164",
    "REDACTION_SENTINEL",
    "PII_HMAC_KEY_ENV",
]

#: Environment variable holding the salt/key for the redaction HMAC.
PII_HMAC_KEY_ENV = "WHATSAPP_PII_HMAC_KEY"

#: Grep-able sentinel returned on ANY redaction failure. Distinct from every
#: ``wa:``-prefixed success token, so an audit scan can detect failures
#: (``grep '<unredactable wa identity>'``) without ever seeing a raw number.
REDACTION_SENTINEL = "<unredactable wa identity>"

# A normalized E.164 number is digits only (the leading '+' is stripped). WhatsApp
# wa_ids are also bare digit strings, so both surfaces normalize identically.
_NON_DIGITS = re.compile(r"\D+")


def normalize_e164(raw: str) -> str:
    """Normalize a phone number / ``wa_id`` to a canonical bare-digit form.

    Strips a leading ``+``, all separators (spaces, dashes, parens, dots), and
    surrounding whitespace, leaving only the digits. Applied IDENTICALLY to the
    stored directory keys (todo 04), incoming inbound ``wa_id``s (todo 05), and
    outbound recipients (todo 03) so the redaction token is stable across send
    and receive.

    Raises :class:`ValueError` if the input contains no digits (un-normalizable)
    — callers in the redaction path catch this and return the sentinel; the
    raised message NEVER echoes the raw input.
    """
    if not isinstance(raw, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"normalize_e164 requires a str; got {type(raw).__name__}"
        )  # pyright: ignore[reportUnreachable]
    digits = _NON_DIGITS.sub("", raw.strip())
    if not digits:
        # Do NOT include the raw value in the message — it may be PII.
        raise ValueError("normalize_e164 received a value with no digits")
    return digits


def _hmac_key() -> bytes:
    """Read the redaction key from the environment.

    Raises :class:`KeyError` when absent; the redaction path catches it and
    returns the sentinel rather than a raw fallback (invariant 3).
    """
    key = os.environ.get(PII_HMAC_KEY_ENV)
    if not key:
        raise KeyError(f"{PII_HMAC_KEY_ENV} is not set in the environment")
    return key.encode("utf-8")


def redact_phone(raw: str) -> str:
    """Redact a phone number / ``wa_id`` to a stable ``wa:<first-8-hex>`` token.

    Deterministic and key-stable within a process: the same ``raw`` input yields
    the same token under a fixed ``WHATSAPP_PII_HMAC_KEY``; a different key yields
    a different token. On ANY failure (missing key, un-normalizable input) returns
    :data:`REDACTION_SENTINEL` — NEVER the raw number, NEVER an exception that
    leaks the raw value.
    """
    try:
        normalized = normalize_e164(raw)
        key = _hmac_key()
    except (TypeError, ValueError, KeyError):
        # Any failure path collapses to the grep-able sentinel. The raw value is
        # never returned and never re-raised in a leaking message.
        return REDACTION_SENTINEL
    digest = hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"wa:{digest[:8]}"
