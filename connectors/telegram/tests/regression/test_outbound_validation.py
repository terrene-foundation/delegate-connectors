# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Regression: outbound content validation fires at the construction boundary.

The shipped validation contract (``validation.py`` + ``OutboundMessage``):

- ``text`` rejects CR, NUL, and any other disallowed C0/C1 control char (tab +
  newline are permitted) and rejects > 4096 UTF-16 code units.
- ``chat_id`` rejects a malformed string (a non-``@channel`` non-integer) and a
  ``bool``.

Every validation failure raises ``MessageValidationError`` at
``OutboundMessage.__post_init__`` — BEFORE any Bot API request is constructed.
On the ``invoke`` hot path the same boundary fires (``invoke`` builds an
``OutboundMessage`` from the payload), so a crafted ``text`` / ``chat_id``
raises with ZERO ``sendMessage`` fired at the double.

Behavioral (NOT source-grep) per ``rules/testing.md``: each test constructs the
real ``OutboundMessage`` / drives the real ``invoke`` and asserts the typed
raise + zero-send. Tests only the SHIPPED validation surface (per
``rules/spec-accuracy.md``).
"""

from __future__ import annotations

import pytest

from delegate_connectors.telegram.transport import OutboundMessage
from delegate_connectors.telegram.validation import (
    MAX_TEXT_UTF16_UNITS,
    MessageValidationError,
)

# Module-level mark is `regression` ONLY. The construction-boundary tests below
# are SYNCHRONOUS (they assert a raise at OutboundMessage construction, no await),
# so they MUST NOT carry the asyncio mark — under `asyncio_mode="auto"` a
# module-level asyncio mark would flag every sync test with a PytestWarning. The
# two async `invoke`-hot-path tests carry `@pytest.mark.asyncio` explicitly.
pytestmark = pytest.mark.regression

_RECIPIENT_CHAT_ID = 555000


# ── Construction-boundary: typed raise BEFORE any HTTP ─────────────────────


@pytest.mark.parametrize(
    "bad_text",
    [
        "has\rcarriage-return",
        "has\x00null-byte",
        "has\x07bell-control",
        "has\x1bescape-control",
    ],
)
def test_control_char_text_raises_at_construction(bad_text):
    """CR / NUL / other C0 control chars raise at OutboundMessage construction."""
    with pytest.raises(MessageValidationError):
        OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text=bad_text)


def test_over_length_text_raises_at_construction():
    """Text exceeding 4096 UTF-16 code units raises at construction."""
    over = "a" * (MAX_TEXT_UTF16_UNITS + 1)
    with pytest.raises(MessageValidationError):
        OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text=over)


def test_empty_text_raises_at_construction():
    """Empty text raises at construction (the Bot API rejects an empty message)."""
    with pytest.raises(MessageValidationError):
        OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text="")


@pytest.mark.parametrize(
    "bad_chat_id",
    [
        "not-an-integer",
        "@",  # handle with no username body
        "@bad handle",  # whitespace in handle
        " 123",  # leading whitespace
        True,  # bool is an int subclass but never a valid chat id
    ],
)
def test_malformed_chat_id_raises_at_construction(bad_chat_id):
    """A malformed chat_id raises at OutboundMessage construction."""
    with pytest.raises(MessageValidationError):
        OutboundMessage(chat_id=bad_chat_id, text="hello")


def test_valid_message_constructs_without_raising():
    """Control: a valid text + chat_id constructs cleanly (tab + newline allowed)."""
    msg = OutboundMessage(chat_id=_RECIPIENT_CHAT_ID, text="line1\nline2\twith-tab")
    assert msg.text == "line1\nline2\twith-tab"
    # A @channelusername handle is also valid.
    handle = OutboundMessage(chat_id="@my_channel", text="hi")
    assert handle.chat_id == "@my_channel"


# ── invoke hot path: typed raise + ZERO send fired ─────────────────────────


@pytest.mark.asyncio
async def test_invoke_with_bad_text_raises_and_no_send(
    telegram_regression_composed, botapi_double
):
    """A crafted text on the invoke hot path raises with ZERO sendMessage fired."""
    composed = telegram_regression_composed

    with pytest.raises(MessageValidationError):
        await composed.connector.invoke(
            {"chat_id": _RECIPIENT_CHAT_ID, "text": "carriage\rreturn"},
            identity=composed.identity,
            envelope=composed.dispatch_surface.envelope,
        )
    # The validation raised at OutboundMessage construction, AFTER auth but
    # BEFORE the transport.send — the double recorded zero sendMessage.
    assert botapi_double.send_requests == []
    assert botapi_double.delivered == []


@pytest.mark.asyncio
async def test_invoke_with_bad_chat_id_raises_and_no_send(
    telegram_regression_composed, botapi_double
):
    """A malformed chat_id on the invoke hot path raises with ZERO send fired."""
    composed = telegram_regression_composed

    with pytest.raises(MessageValidationError):
        await composed.connector.invoke(
            {"chat_id": "not-a-valid-chat-id", "text": "hello"},
            identity=composed.identity,
            envelope=composed.dispatch_surface.envelope,
        )
    assert botapi_double.send_requests == []
    assert botapi_double.delivered == []
