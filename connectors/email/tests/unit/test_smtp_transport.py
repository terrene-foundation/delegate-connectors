# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the SMTP transport (no network)."""

from __future__ import annotations

import pytest

from delegate_connectors.email.smtp import (
    OutboundMessage,
    SmtpConfig,
    SmtpConfigError,
)


def test_outbound_message_to_mime_is_well_formed():
    msg = OutboundMessage(
        sender="alice@example.com",
        recipient="bob@example.com",
        subject="Greetings",
        body="Hello, Bob.",
    )
    mime = msg.to_mime()
    assert mime["From"] == "alice@example.com"
    assert mime["To"] == "bob@example.com"
    assert mime["Subject"] == "Greetings"
    assert mime["Message-ID"]  # auto-generated, non-empty
    assert mime.get_content().strip() == "Hello, Bob."


def test_outbound_message_id_is_stable_per_instance():
    msg = OutboundMessage(sender="a@b.com", recipient="c@d.com", subject="s", body="b")
    assert msg.to_mime()["Message-ID"] == msg.message_id


def test_smtp_config_from_env_requires_host(monkeypatch):
    monkeypatch.delenv("EMAIL_SMTP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_SMTP_PORT", "1025")
    with pytest.raises(SmtpConfigError, match="EMAIL_SMTP_HOST"):
        SmtpConfig.from_env()


def test_smtp_config_from_env_requires_integer_port(monkeypatch):
    monkeypatch.setenv("EMAIL_SMTP_HOST", "localhost")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "not-a-number")
    with pytest.raises(SmtpConfigError, match="integer"):
        SmtpConfig.from_env()


def test_smtp_config_reads_credentials_from_env_only(monkeypatch):
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_SMTP_USER", "u")
    monkeypatch.setenv("EMAIL_SMTP_PASSWORD", "p")
    monkeypatch.setenv("EMAIL_SMTP_USE_TLS", "true")
    cfg = SmtpConfig.from_env()
    assert cfg.host == "smtp.test"
    assert cfg.port == 587
    assert cfg.username == "u"
    assert cfg.password == "p"
    assert cfg.use_tls is True
