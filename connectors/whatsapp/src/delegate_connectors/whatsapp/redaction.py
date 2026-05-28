# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Phone-number PII redaction (binding security floor).

Phone numbers and ``wa_id``s are PII. Every audit payload (the canonical bytes
of a ``SignedActionEnvelope`` / ``AttestedReadReceipt``), every ledger record,
and every log line MUST carry a stable salted-HMAC-SHA256 token of the form
``wa:<first-8-hex>`` — NEVER the raw E.164. The raw number lives only in the
transient outbound HTTPS body to Meta and is dropped after the send.

This module exposes a DUAL CONTRACT for the PII HMAC key — startup-loud +
runtime-soft — and the connector MUST honor both halves:

1. **Startup gate (LOUD, fails the process):** the connector's ``__init__``
   (todo 07) MUST call :meth:`RedactionConfig.from_env` so an installation with
   no ``WHATSAPP_PII_HMAC_KEY`` set REFUSES to start. Symmetric with the
   existing ``_require_env`` guards on ``WHATSAPP_APP_SECRET`` and
   ``WHATSAPP_WEBHOOK_VERIFY_TOKEN`` in :mod:`webhook` — the PII key has equal
   load-bearing status (every audit/log line depends on it). Missing or empty
   raises :class:`RedactionConfigError`.
2. **Per-message redaction (FAIL-SOFT, returns sentinel):** :func:`redact_phone`
   preserves its current contract: ANY runtime failure — missing key,
   un-normalizable input — returns the grep-able sentinel
   :data:`REDACTION_SENTINEL` rather than raising or leaking the raw number.
   This is single-rotation-glitch robustness: a transient unset key at one
   call site MUST NOT crash the connector or surface the raw PII in an error
   message. The startup gate above prevents the *systematic* missing-key case;
   the sentinel handles the *transient* one.

:func:`redact_phone` is deterministic + key-stable within a process: the same
raw number yields the same token, keyed by ``WHATSAPP_PII_HMAC_KEY`` (env-only).

:func:`normalize_e164` is the shared normalization routine reused by the
principal directory (todo 04) and the future Cloud API send (todo 03), so the
redaction token is stable across both the send and receive surfaces.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass

__all__ = [
    "redact_phone",
    "normalize_e164",
    "REDACTION_SENTINEL",
    "PII_HMAC_KEY_ENV",
    "RedactionConfig",
    "RedactionConfigError",
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


class RedactionConfigError(ValueError):
    """Raised when required PII-redaction configuration is absent at startup.

    Symmetric with :class:`delegate_connectors.whatsapp.webhook.WebhookConfigError`:
    both are the typed startup-refusal class for credentials whose absence
    would silently degrade the security floor. Subclasses ``ValueError`` so
    callers that already catch ``ValueError`` (e.g., generic config-load error
    handlers) see it, but a typed ``except RedactionConfigError`` is the
    canonical surface for the connector's ``__init__``.
    """


def _require_env(name: str) -> str:
    """Read an env-var and raise loudly when missing or empty.

    Mirrors the helper shape in :mod:`webhook` (``_require_env``) so the three
    load-bearing WhatsApp credentials — ``WHATSAPP_APP_SECRET``,
    ``WHATSAPP_WEBHOOK_VERIFY_TOKEN``, ``WHATSAPP_PII_HMAC_KEY`` — refuse-on-
    absent with the same shape. Kept local to redaction.py per the todo's
    intent (do NOT factor out yet); when a third surface lands we will
    consolidate into a shared helper.
    """
    value = os.environ.get(name)
    if value is None or value == "":
        raise RedactionConfigError(
            f"{name} MUST be set in the environment (credentials are env-only; "
            "no silent default)"
        )
    return value


@dataclass(frozen=True, slots=True)
class RedactionConfig:
    """PII-redaction configuration, resolved from the environment at startup.

    The startup half of the dual contract documented in the module docstring:
    :meth:`from_env` is the load-bearing gate the connector's ``__init__``
    (todo 07) MUST invoke so an installation with no ``WHATSAPP_PII_HMAC_KEY``
    set REFUSES to start. The runtime half — :func:`redact_phone` returning
    the sentinel on per-message failure — is preserved unchanged.
    """

    hmac_key: str

    @classmethod
    def from_env(cls) -> "RedactionConfig":
        """Resolve the redaction config from the environment, loudly.

        Raises :class:`RedactionConfigError` when ``WHATSAPP_PII_HMAC_KEY`` is
        unset OR empty. Symmetric with
        :meth:`delegate_connectors.whatsapp.webhook.WebhookConfig.from_env`.
        """
        return cls(hmac_key=_require_env(PII_HMAC_KEY_ENV))


def _hmac_key() -> bytes:
    """Read the redaction key from the environment.

    Raises :class:`KeyError` when absent; the redaction path catches it and
    returns the sentinel rather than a raw fallback (the runtime-soft half of
    the dual contract — startup-loud is :meth:`RedactionConfig.from_env`).
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
