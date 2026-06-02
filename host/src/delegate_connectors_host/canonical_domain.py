# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Producer-side canonical-domain reject gate (Phase-0, P0-08a hardening).

``specs/canonical-signing-bytes.md`` §1.2–§1.5 + §5 mandate that the **producer**
REJECT a payload — before it is ever signed — when it contains any value the
frozen v1 wire form cannot carry interoperably:

- a **float** (§1.4 — cross-language float formatting is unpinned; ``NaN`` /
  ``Infinity`` / ``-Infinity`` additionally emit non-JSON tokens that a Rust
  ``serde_json`` verifier rejects on parse: the "permanently unverifiable, no
  producer-side error" footgun freezing v1 exists to close),
- an **integer outside ``[-(2^53-1), 2^53-1]``** (§1.3 — a JS ``JSON.parse``
  silently corrupts ``≥2^53``; JavaScript consumers are in scope),
- a **non-string object key** (§1.2 — Python sorts typed keys numerically then
  stringifies, an order no string-keyed verifier reproduces),
- a **lone surrogate** in a string (§1.5 — ``json.dumps`` does not raise; the
  failure surfaces only at ``.encode("utf-8")`` as an opaque ``UnicodeEncodeError``).

§1.4 places this enforcement "**at the connector boundary** (not rely on
result-shape coincidence)". The shared P0-04 helpers (``build_action_signing_bytes``
/ ``build_read_signing_bytes``) ARE that boundary for this repo — every host
receipt (the new host-observation seam AND the reference connectors) is produced
through them. This module is the validator they call BEFORE handing the payload
to the canonical encoder, so a non-conformant payload raises a typed
:class:`NonConformantPayloadError` rather than silently producing bytes that
"look signed" but verify nowhere.

Why a host-side gate (not a spine edit)
=======================================
The frozen encoder (``kailash.trust._json.canonical_json_dumps``) is a SEPARATE
repo (repo-scope discipline) and currently calls ``json.dumps`` WITHOUT
``allow_nan=False`` and performs no integer-domain / key-type validation — so the
reject contract §1 marks REQUIRED is unenforced there. This module enforces the
contract at the host producer boundary §1.4 designates, with ZERO spine edits and
WITHOUT re-implementing the canonical ENCODING (key ordering / escaping stay the
frozen encoder's job). It enforces the spec's normative §5 reject suite; it does
not diverge from it — a conforming Rust producer enforces the same §5 suite.

This is the producer half. The verifier-side duplicate-key rejection (§1.7) is a
separate parser concern (a Python ``dict`` cannot hold duplicate keys, so it
cannot arise on the producer path) and is out of scope here.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["NonConformantPayloadError", "assert_canonical_signing_domain"]

# JavaScript ``Number.MAX_SAFE_INTEGER`` — the inclusive integer bound (§1.3).
_MAX_SAFE_INT = 2**53 - 1


class NonConformantPayloadError(ValueError):
    """A payload value cannot be carried by the frozen v1 canonical wire form.

    Raised by :func:`assert_canonical_signing_domain` at the producer boundary
    (the shared signing-byte helpers) BEFORE signing, so a non-conformant payload
    fails loudly with an actionable message instead of producing bytes that are
    silently corrupted or permanently unverifiable across implementations.

    Subclasses :class:`ValueError` so a generic receipt-construction handler still
    catches it, while the concrete type names the specific conformance failure.
    """


def assert_canonical_signing_domain(obj: Any, *, _path: str = "$") -> None:
    """Raise :class:`NonConformantPayloadError` if ``obj`` violates §1.2–§1.5.

    Recursively walks ``obj`` (the receipt ``payload`` / read ``manifest`` and
    every nested value) and enforces the producer-side reject suite. Returns
    ``None`` when the whole structure conforms; the caller then proceeds to the
    frozen canonical encoder. ``_path`` tracks the location for the error message
    and is internal (callers pass only ``obj``).

    Allowed leaf types: ``str`` (no lone surrogates), ``bool``, ``int`` within
    ``[-(2^53-1), 2^53-1]``, and ``None``. Allowed containers: ``Mapping`` (string
    keys only) and non-``str``/``bytes`` ``Sequence`` (lists/tuples). Everything
    else — notably any ``float`` — is rejected.
    """
    # bool is a subclass of int and renders as the lowercase literals true/false
    # (§1.6) — it is allowed and MUST be checked before the int branch so True/1
    # are not conflated.
    if obj is None or isinstance(obj, bool):
        return

    if isinstance(obj, str):
        _reject_lone_surrogate(obj, _path)
        return

    if isinstance(obj, int):
        if abs(obj) > _MAX_SAFE_INT:
            raise NonConformantPayloadError(
                f"integer at {_path} is {obj}, outside the JS-safe domain "
                f"[-(2^53-1), 2^53-1] (§1.3); carry it as a decimal string or "
                f"integer minor-units, never a bare JSON number"
            )
        return

    if isinstance(obj, float):
        raise NonConformantPayloadError(
            f"float at {_path} ({obj!r}) is forbidden in a signed pre-image "
            f"(§1.4 — ALL floats are banned: cross-language float formatting is "
            f"unpinned, and the NaN/Infinity subset additionally emit non-JSON "
            f"tokens a serde_json verifier rejects on parse); carry decimals as "
            f'strings ("10.50") or integer minor-units'
        )

    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise NonConformantPayloadError(
                    f"object key {key!r} at {_path} is a "
                    f"{type(key).__name__}, not a string (§1.2 — non-string keys "
                    f"are FORBIDDEN; they sort/stringify in an order no "
                    f"string-keyed verifier reproduces)"
                )
            _reject_lone_surrogate(key, f"{_path}.{key}")
            assert_canonical_signing_domain(value, _path=f"{_path}.{key}")
        return

    # Lists/tuples — but NOT str/bytes (str handled above; bytes is not JSON).
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        for index, item in enumerate(obj):
            assert_canonical_signing_domain(item, _path=f"{_path}[{index}]")
        return

    raise NonConformantPayloadError(
        f"value at {_path} has type {type(obj).__name__!r}, which is not a "
        f"canonical-JSON type (allowed: str, bool, int-in-range, None, mapping "
        f"with string keys, list/tuple)"
    )


def _reject_lone_surrogate(text: str, path: str) -> None:
    """Raise if ``text`` contains a lone surrogate (§1.5).

    ``json.dumps`` does not raise on a lone surrogate; the failure surfaces only
    at ``.encode("utf-8")`` as an opaque ``UnicodeEncodeError``. We probe the
    strict UTF-8 encoding here and convert that into a typed, located reject so
    the producer fails with an actionable message at the canonical boundary.
    """
    try:
        text.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise NonConformantPayloadError(
            f"string at {path} contains a lone surrogate ({exc.reason}); lone "
            f"surrogates (U+D800–U+DFFF) MUST be rejected (§1.5) — they make the "
            f"strict-UTF-8 pre-image unencodable and the receipt unverifiable"
        ) from exc
