# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for pure message-content validation (no transport)."""

from __future__ import annotations

import pytest

from delegate_connectors.telegram.validation import (
    MAX_TEXT_UTF16_UNITS,
    MessageValidationError,
    text_utf16_units,
    validate_chat_id,
    validate_text,
)


# --- text_utf16_units --------------------------------------------------------


def test_utf16_units_counts_bmp_as_one():
    assert text_utf16_units("hello") == 5
    assert text_utf16_units("é") == 1  # BMP


def test_utf16_units_counts_astral_as_two():
    # An emoji outside the BMP is a surrogate pair => 2 UTF-16 code units.
    assert text_utf16_units("\U0001f600") == 2


# --- validate_text -----------------------------------------------------------


def test_validate_text_accepts_clean_string_and_returns_it():
    assert validate_text("a clean message") == "a clean message"


def test_validate_text_permits_tab_and_newline():
    assert validate_text("line1\nline2\twith tab") == "line1\nline2\twith tab"


@pytest.mark.parametrize(
    "bad",
    [
        "carriage\rreturn",  # CR rejected (newline is allowed, CR is not)
        "null\x00byte",
        "bell\x07char",
        "vertical\x0btab",
        "form\x0cfeed",
        "c1\x85control",  # NEL (C1)
    ],
)
def test_validate_text_rejects_control_characters(bad):
    with pytest.raises(MessageValidationError):
        validate_text(bad)


def test_validate_text_rejects_empty():
    with pytest.raises(MessageValidationError):
        validate_text("")


def test_validate_text_rejects_non_str():
    with pytest.raises(MessageValidationError):
        validate_text(123)  # type: ignore[arg-type]


def test_validate_text_accepts_exactly_at_limit():
    text = "a" * MAX_TEXT_UTF16_UNITS
    assert validate_text(text) == text


def test_validate_text_rejects_one_over_limit_bmp():
    with pytest.raises(MessageValidationError):
        validate_text("a" * (MAX_TEXT_UTF16_UNITS + 1))


def test_validate_text_counts_emoji_as_two_units_for_the_bound():
    # 2048 astral emoji == 4096 UTF-16 units == exactly at the limit.
    at_limit = "\U0001f600" * (MAX_TEXT_UTF16_UNITS // 2)
    assert validate_text(at_limit) == at_limit
    # One more emoji pushes to 4098 units => over the limit, even though the
    # code-POINT count (2049) is far below 4096.
    over = "\U0001f600" * (MAX_TEXT_UTF16_UNITS // 2 + 1)
    with pytest.raises(MessageValidationError):
        validate_text(over)


# --- validate_chat_id --------------------------------------------------------


def test_validate_chat_id_accepts_positive_int():
    assert validate_chat_id(123456789) == 123456789


def test_validate_chat_id_accepts_negative_int():
    assert validate_chat_id(-100200300) == -100200300


def test_validate_chat_id_accepts_integer_string():
    assert validate_chat_id("123456789") == "123456789"
    assert validate_chat_id("-100200300") == "-100200300"


def test_validate_chat_id_accepts_channel_handle():
    assert validate_chat_id("@my_channel") == "@my_channel"


@pytest.mark.parametrize(
    "bad",
    [
        "@",  # handle with no username body
        "@bad-handle",  # '-' not allowed in a channel username
        "plainusername",  # bare username is never a valid chat_id
        "12.5",  # not an integer literal
        " 123 ",  # surrounding whitespace
        "",  # empty
        "@with space",
    ],
)
def test_validate_chat_id_rejects_malformed_string(bad):
    with pytest.raises(MessageValidationError):
        validate_chat_id(bad)


def test_validate_chat_id_rejects_bool():
    with pytest.raises(MessageValidationError):
        validate_chat_id(True)


def test_validate_chat_id_rejects_non_int_non_str():
    with pytest.raises(MessageValidationError):
        validate_chat_id(12.5)  # type: ignore[arg-type]
