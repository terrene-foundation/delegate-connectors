# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the IMAP transport parsing (no network)."""

from __future__ import annotations

import pytest

from delegate_connectors.email.imap import (
    ImapConfig,
    ImapConfigError,
    _select_rfc822_literal,
    parse_rfc822,
)

_RAW = (
    b"From: Alice <alice@example.com>\r\n"
    b"To: bob@example.com\r\n"
    b"Subject: Hello\r\n"
    b"Message-ID: <abc@host>\r\n"
    b"\r\n"
    b"Hi Bob, this is the body.\r\n"
)


def test_parse_rfc822_extracts_normalized_fields():
    msg = parse_rfc822(_RAW)
    assert msg.from_addr == "alice@example.com"  # display name stripped
    assert msg.to_addr == "bob@example.com"
    assert msg.subject == "Hello"
    assert msg.message_id == "<abc@host>"
    assert "Hi Bob" in msg.body
    assert msg.headers["Subject"] == "Hello"


def test_parse_rfc822_decodes_rfc2047_headers():
    raw = (
        b"From: =?utf-8?q?J=C3=BCrgen?= <jurgen@host.de>\r\n"
        b"To: a@b.com\r\n"
        b"Subject: =?utf-8?q?Caf=C3=A9?=\r\n"
        b"\r\n"
        b"body"
    )
    msg = parse_rfc822(raw)
    assert msg.subject == "Café"
    assert msg.from_addr == "jurgen@host.de"


def test_parse_rfc822_rejects_non_bytes():
    with pytest.raises(TypeError):
        parse_rfc822("not bytes")  # type: ignore[arg-type]


def test_select_rfc822_literal_skips_framing_lines():
    lines = [b"* 1 FETCH (RFC822 {120}", _RAW, b")"]
    assert _select_rfc822_literal(lines) == _RAW


def test_select_rfc822_literal_picks_largest_candidate():
    small = b"a\r\n\r\nb"
    big = _RAW
    assert _select_rfc822_literal([small, big]) == big


def test_imap_config_from_env_requires_host(monkeypatch):
    monkeypatch.delenv("EMAIL_IMAP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_IMAP_PORT", "1143")
    with pytest.raises(ImapConfigError, match="EMAIL_IMAP_HOST"):
        ImapConfig.from_env()
