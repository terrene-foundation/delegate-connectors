# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Pure message-content validation for the Bot API send boundary.

These checks are the construction-boundary validation the Bot API requires of an
outbound ``sendMessage`` body — control characters rejected, ``text`` bounded to
4096 UTF-16 code units, ``chat_id`` constrained to an integer-or-``@channel``
string. The Bot API takes a JSON body (there is no SMTP-style header-injection
analog), so the message is validated at construction BEFORE any byte transits
the network.

This module is deliberately PURE: it imports nothing beyond the standard library
and has NO transport dependency. The ``httpx``-backed transport's
``OutboundMessage`` consumes :func:`validate_text` + :func:`validate_chat_id` in
its ``__post_init__`` so the single boundary covers every send route (the
``invoke`` hot path and any direct ``write`` / ``send`` call construct an
``OutboundMessage`` first).

Validation failures raise :class:`MessageValidationError` (a ``ValueError``
subclass) so the caller sees a typed, actionable error rather than an opaque Bot
API ``400``.
"""

from __future__ import annotations

__all__ = [
    "MessageValidationError",
    "MAX_TEXT_UTF16_UNITS",
    "text_utf16_units",
    "validate_text",
    "validate_chat_id",
]

# The Bot API caps sendMessage `text` at 4096 UTF-16 code units. Telegram counts
# length in UTF-16 code units, NOT Unicode code points: a BMP character is 1
# unit; an astral character (e.g. most emoji) is 2 units (a surrogate pair).
MAX_TEXT_UTF16_UNITS = 4096

# Allowed control characters inside `text`. Telegram permits newline (U+000A) and
# tab (U+0009) in message bodies; carriage return and all other C0/C1 control
# characters are rejected at the construction boundary.
_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n"})


class MessageValidationError(ValueError):
    """Raised when an outbound message field fails the construction-boundary check.

    A ``ValueError`` subclass so existing ``except ValueError`` handlers still
    catch it, while callers that want the specific class can catch
    :class:`MessageValidationError` directly.
    """


def text_utf16_units(text: str) -> int:
    """Count the UTF-16 code units in ``text`` (Telegram's length unit).

    A BMP character counts as 1; an astral character (surrogate pair) counts as
    2. This is the same unit the Bot API uses to enforce the 4096 cap, so
    counting code POINTS (``len(text)``) would under-count emoji-heavy strings
    and let an over-length body reach the API.
    """
    if not isinstance(text, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"text_utf16_units requires a str; got {type(text).__name__}"
        )  # pyright: ignore[reportUnreachable]
    # UTF-16-LE encodes each code unit as exactly 2 bytes; dividing the byte
    # length by 2 yields the code-unit count without a BOM.
    return len(text.encode("utf-16-le")) // 2


def _is_disallowed_control_char(ch: str) -> bool:
    """True iff ``ch`` is a C0/C1 control character that is NOT explicitly allowed."""
    # C0 controls: U+0000–U+001F. C1 controls: U+007F–U+009F.
    code = ord(ch)
    if ch in _ALLOWED_CONTROL_CHARS:
        return False
    return code <= 0x1F or 0x7F <= code <= 0x9F


def validate_text(text: str) -> str:
    """Validate an outbound message ``text`` and return it unchanged on success.

    Rejects (raising :class:`MessageValidationError`):

    * a non-``str`` value;
    * an empty ``text`` (the Bot API rejects an empty message);
    * any disallowed control character (CR, NUL, and all other C0/C1 controls;
      tab and newline are permitted);
    * a ``text`` longer than :data:`MAX_TEXT_UTF16_UNITS` UTF-16 code units.

    Returns ``text`` so it composes as ``self.text = validate_text(text)``.
    """
    if not isinstance(text, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise MessageValidationError(
            f"text MUST be a str; got {type(text).__name__}"
        )  # pyright: ignore[reportUnreachable]
    if text == "":
        raise MessageValidationError("text MUST NOT be empty")
    for ch in text:
        if _is_disallowed_control_char(ch):
            raise MessageValidationError(
                f"text contains a disallowed control character U+{ord(ch):04X} "
                "(only tab and newline are permitted)"
            )
    units = text_utf16_units(text)
    if units > MAX_TEXT_UTF16_UNITS:
        raise MessageValidationError(
            f"text is {units} UTF-16 code units; the Bot API limit is "
            f"{MAX_TEXT_UTF16_UNITS}"
        )
    return text


def validate_chat_id(chat_id: int | str) -> int | str:
    """Validate an outbound ``chat_id`` and return it unchanged on success.

    The Bot API accepts a ``chat_id`` that is EITHER an integer (a numeric
    user / chat id, which may be negative for groups / channels) OR a string of
    the form ``@channelusername`` (a public channel / supergroup handle).

    Rejects (raising :class:`MessageValidationError`):

    * a ``bool`` (``True`` / ``False`` are ``int`` subclasses but are never a
      valid chat id);
    * any non-``int`` / non-``str`` value;
    * a string that is neither a ``@channelusername`` handle nor a base-10
      integer literal;
    * an empty / whitespace-only string, or a ``@``-prefixed handle with no
      username body.

    Returns ``chat_id`` so it composes as ``self.chat_id = validate_chat_id(x)``.
    """
    # bool is an int subclass; reject it before the int branch.
    if isinstance(chat_id, bool):
        raise MessageValidationError("chat_id MUST NOT be a bool")
    if isinstance(chat_id, int):
        return chat_id
    if isinstance(chat_id, str):
        stripped = chat_id.strip()
        if stripped != chat_id:
            raise MessageValidationError(
                "chat_id string MUST NOT have leading/trailing whitespace"
            )
        if chat_id.startswith("@"):
            handle = chat_id[1:]
            if not handle:
                raise MessageValidationError(
                    "chat_id channel handle MUST have a username after '@'"
                )
            # Public channel/supergroup usernames are [A-Za-z0-9_]; no further
            # '@' inside.
            if not all(c.isalnum() or c == "_" for c in handle):
                raise MessageValidationError(
                    "chat_id channel handle MUST be alphanumeric/underscore "
                    f"after '@'; got {chat_id!r}"
                )
            return chat_id
        # A non-@ string is valid only if it is a base-10 integer literal
        # (optionally signed). Telegram never keys a send on a bare username.
        body = chat_id[1:] if chat_id[:1] in "+-" else chat_id
        if body.isdigit() and body != "":
            return chat_id
        raise MessageValidationError(
            "chat_id string MUST be a '@channelusername' handle or a base-10 "
            f"integer literal; got {chat_id!r}"
        )
    raise MessageValidationError(  # pyright: ignore[reportUnreachable]
        f"chat_id MUST be an int or str; got {type(chat_id).__name__}"
    )
