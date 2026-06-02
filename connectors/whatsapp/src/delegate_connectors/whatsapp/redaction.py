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
   preserves its current contract: ANY runtime failure — absent key,
   un-normalizable input — returns the grep-able sentinel
   :data:`REDACTION_SENTINEL` rather than raising or leaking the raw number.
   This is single-rotation-glitch robustness: a transient absent key at one
   call site MUST NOT crash the connector or surface the raw PII in an error
   message. The startup gate above prevents the *systematic* missing-key case;
   the sentinel handles the *transient* one.

Credential-blindness fix (P0-07): the key is THREADED, not re-read per message
==============================================================================
:func:`redact_phone` takes the HMAC key as an explicit ``hmac_key`` argument
sourced from the STARTUP-validated :class:`RedactionConfig`. It no longer reads
``os.environ`` on every call — the previous per-message ``os.environ.get`` was
both a per-message credential read AND a second source-of-truth that could
diverge from the startup-validated key. Each call site (the connector's
audit-payload redaction, the Cloud API log redaction, the inbound webhook
parse) threads the key it validated once at startup. The fail-soft half is
preserved structurally: an absent/empty ``hmac_key`` yields the sentinel — the
transient-glitch path — without any environment access.

The host's credential broker (``delegate_connectors_host.credential_broker``)
will, in P0-11, mint this key via ``mint_secret('whatsapp_pii_hmac_key')`` and
feed it to :meth:`RedactionConfig` — at which point even the startup
``RedactionConfig.from_env`` env read moves host-side. This shard removes ONLY
the per-message read; the startup ``from_env`` stays here until P0-11 wires it.

:func:`redact_phone` is deterministic + key-stable within a process: the same
raw number under the same threaded ``hmac_key`` yields the same token.

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

    The connector holds this config from startup and THREADS :attr:`hmac_key`
    into every :func:`redact_phone` call (directly or via :meth:`redact`) so the
    per-message path never re-reads ``os.environ`` (P0-07 credential-blindness
    fix). :meth:`redact` is the convenience wrapper that binds the validated key.
    """

    hmac_key: str

    @classmethod
    def from_env(cls) -> "RedactionConfig":
        """Resolve the redaction config from the environment, loudly.

        Raises :class:`RedactionConfigError` when ``WHATSAPP_PII_HMAC_KEY`` is
        unset OR empty. Symmetric with
        :meth:`delegate_connectors.whatsapp.webhook.WebhookConfig.from_env`.

        This is the ONLY remaining env read for the PII key; the per-message
        path takes the validated key as an argument. In P0-11 the host's
        credential broker mints the key (``mint_secret('whatsapp_pii_hmac_key')``)
        and this ``from_env`` is replaced by an injected ``RedactionConfig``.
        """
        return cls(hmac_key=_require_env(PII_HMAC_KEY_ENV))

    def redact(self, raw: str) -> str:
        """Redact ``raw`` using this config's STARTUP-validated key.

        Convenience wrapper binding :attr:`hmac_key` so call sites that hold a
        :class:`RedactionConfig` (the connector, the Cloud API transport, the
        webhook ingest) redact without re-reading the environment.
        """
        return redact_phone(raw, hmac_key=self.hmac_key)


def redact_phone(raw: str, *, hmac_key: str | None) -> str:
    """Redact a phone number / ``wa_id`` to a stable ``wa:<first-8-hex>`` token.

    Deterministic and key-stable within a process: the same ``raw`` input yields
    the same token under a fixed ``hmac_key``; a different key yields a different
    token. The ``hmac_key`` is the STARTUP-validated key threaded from a
    :class:`RedactionConfig` — this function NEVER reads ``os.environ`` (the
    P0-07 credential-blindness fix: no per-message credential read, no second
    source-of-truth that could diverge from the startup-validated key).

    On ANY failure (absent/empty ``hmac_key``, un-normalizable input) returns
    :data:`REDACTION_SENTINEL` — NEVER the raw number, NEVER an exception that
    leaks the raw value. The absent-key path IS the runtime-soft half of the
    dual contract: a transient missing key at one call site collapses to the
    grep-able sentinel rather than crashing the connector or leaking PII.
    """
    if not hmac_key:
        # Runtime-soft half of the dual contract: an absent/empty key at the
        # per-message call site yields the sentinel — never the raw value,
        # never an environment read. The startup gate
        # (RedactionConfig.from_env) prevents the SYSTEMATIC missing-key case.
        return REDACTION_SENTINEL
    try:
        normalized = normalize_e164(raw)
    except (TypeError, ValueError):
        # Un-normalizable input collapses to the grep-able sentinel. The raw
        # value is never returned and never re-raised in a leaking message.
        return REDACTION_SENTINEL
    digest = hmac.new(
        hmac_key.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"wa:{digest[:8]}"
