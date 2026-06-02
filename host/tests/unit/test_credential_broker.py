# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the connector-agnostic ``CredentialBroker`` (P0-07).

The broker is the host-side surface that mints injectable handles for the
connector. Two minting surfaces, with a deliberate credential-blindness
distinction:

* :meth:`CredentialBroker.bind_transport` — the credential-BLIND path. The host
  resolves the secret from its env, calls the connector-supplied ``build(creds)``
  to construct a transport, and returns a :class:`BoundTransport` the connector
  cannot introspect. The connector gets ``send`` / ``fetch``, NEVER the token.
* :meth:`CredentialBroker.mint_secret` — the host-PROVIDED-config path. Returns
  a secret value the connector must USE directly (the PII-HMAC key it needs to
  compute HMACs). NOT credential-blind — it is host-owned config, surfaced.

Every test injects an env ``dict`` (the broker NEVER touches the real
``os.environ`` here), exercises the fail-closed + grant-scoping contracts, and
verifies the BoundTransport minted by ``bind_transport`` does not leak the
token.
"""

from __future__ import annotations

import pickle

import pytest

from delegate_connectors_host.bound_transport import BoundTransport
from delegate_connectors_host.credential_broker import (
    CredentialBroker,
    MissingCredentialError,
    UngrantedCredentialError,
    UnknownCredentialClassError,
)

# ── A representative env dict covering EVERY registered credential class ──────
# Injected into the broker so no test ever reads the real environment.
_FULL_ENV = {
    # email — smtp + imap
    "EMAIL_SMTP_HOST": "smtp.example.com",
    "EMAIL_SMTP_PORT": "587",
    "EMAIL_SMTP_USER": "smtp-user",
    "EMAIL_SMTP_PASSWORD": "smtp-secret-token",
    "EMAIL_SMTP_USE_TLS": "true",
    "EMAIL_IMAP_HOST": "imap.example.com",
    "EMAIL_IMAP_PORT": "993",
    "EMAIL_IMAP_USER": "imap-user",
    "EMAIL_IMAP_PASSWORD": "imap-secret-token",
    "EMAIL_IMAP_USE_TLS": "true",
    # slack
    "SLACK_BOT_TOKEN": "xoxb-slack-secret",
    "SLACK_API_BASE_URL": "https://slack.example.com/api",
    # telegram
    "TELEGRAM_BOT_TOKEN": "telegram-bot-secret",
    "TELEGRAM_API_BASE": "https://tg.example.com",
    # whatsapp — four credential classes
    "WHATSAPP_ACCESS_TOKEN": "wa-access-secret",
    "WHATSAPP_PHONE_NUMBER_ID": "1234567890",
    "WHATSAPP_GRAPH_VERSION": "18.0",
    "WHATSAPP_APP_SECRET": "wa-app-secret",
    "WHATSAPP_WEBHOOK_VERIFY_TOKEN": "wa-verify-token",
    "WHATSAPP_PII_HMAC_KEY": "wa-pii-hmac-key-min-len",
}


def _broker(**overrides: str) -> CredentialBroker:
    """A broker over a COPY of the full env, with optional per-test overrides."""
    env = dict(_FULL_ENV)
    env.update(overrides)
    return CredentialBroker(env=env)


# ── A trivial transport the connector-supplied build() returns ───────────────
class _SpyTransport:
    """Records the creds it was built with so a test can assert blindness.

    A deterministic data endpoint, NOT a mock: it exposes ``send`` / ``fetch``
    that close over (and never re-expose) the brokered secret, plus a public
    ``last_send`` / ``last_fetch`` for the test to inspect the call-through.
    """

    def __init__(self, creds: dict[str, str]) -> None:
        self._token = creds["password"]
        self.last_send: object = None
        self.last_fetch: object = None

    async def send(self, payload: object) -> str:
        self.last_send = payload
        # The transport CAN use the token internally — that's the whole point.
        return f"sent:{payload}:{self._token}"

    async def fetch(self, query: object) -> str:
        self.last_fetch = query
        return f"fetched:{query}:{self._token}"


# ── bind_transport — the credential-BLIND path ───────────────────────────────


@pytest.mark.asyncio
async def test_bind_transport_returns_bound_transport_handle():
    broker = _broker()
    built: list[_SpyTransport] = []

    def build(creds: dict[str, str]) -> _SpyTransport:
        t = _SpyTransport(creds)
        built.append(t)
        return t

    handle = broker.bind_transport("smtp", build)
    assert isinstance(handle, BoundTransport)
    # The host resolved the smtp creds and handed them to build().
    assert len(built) == 1


@pytest.mark.asyncio
async def test_bind_transport_send_and_fetch_call_through():
    broker = _broker()
    handle = broker.bind_transport("smtp", _SpyTransport)

    sent = await handle.send("hello")
    fetched = await handle.fetch("inbox")
    # The handle forwards to the real transport's send/fetch.
    assert sent.startswith("sent:hello:")
    assert fetched.startswith("fetched:inbox:")


@pytest.mark.asyncio
async def test_bind_transport_minted_handle_does_not_leak_token():
    broker = _broker(EMAIL_SMTP_PASSWORD="ultra-secret-smtp-token")
    handle = broker.bind_transport("smtp", _SpyTransport)

    # No .config / .password / .token attribute exposes the secret.
    assert not hasattr(handle, "config")
    assert not hasattr(handle, "password")
    assert not hasattr(handle, "token")
    # __slots__ suppresses __dict__: there is no instance-attribute value to
    # read the secret out of.
    assert not hasattr(handle, "__dict__")
    # repr redacts — never prints the secret.
    assert "ultra-secret-smtp-token" not in repr(handle)
    # Pickling is refused — no serialization escape that dumps the credential.
    with pytest.raises(TypeError):
        pickle.dumps(handle)


@pytest.mark.asyncio
async def test_bind_transport_build_receives_real_creds_from_injected_env():
    broker = _broker(
        EMAIL_SMTP_HOST="injected.smtp.host",
        EMAIL_SMTP_PASSWORD="injected-smtp-pw",
    )
    seen: dict[str, str] = {}

    def build(creds: dict[str, str]) -> _SpyTransport:
        seen.update(creds)
        return _SpyTransport(creds)

    broker.bind_transport("smtp", build)
    # The host minted the creds from the INJECTED env dict, never os.environ.
    assert seen["host"] == "injected.smtp.host"
    assert seen["password"] == "injected-smtp-pw"
    assert seen["user"] == "smtp-user"
    assert seen["port"] == "587"


@pytest.mark.asyncio
async def test_bind_transport_imap_class_mints_imap_creds():
    broker = _broker(EMAIL_IMAP_HOST="imap.injected", EMAIL_IMAP_PASSWORD="imap-pw")
    seen: dict[str, str] = {}

    def build(creds: dict[str, str]) -> _SpyTransport:
        seen.update(creds)
        return _SpyTransport(creds)

    broker.bind_transport("imap", build)
    assert seen["host"] == "imap.injected"
    assert seen["password"] == "imap-pw"


# ── Each registered credential class mints from the injected env ─────────────


@pytest.mark.parametrize(
    "credential_class, required_present",
    [
        ("smtp", ("host", "port", "user", "password")),
        ("imap", ("host", "port", "user", "password")),
        ("slack_bot_token", ("bot_token",)),
        ("telegram_bot_token", ("bot_token",)),
        ("whatsapp_access_token", ("access_token", "phone_number_id")),
        ("whatsapp_app_secret", ("app_secret",)),
        ("whatsapp_webhook_verify_token", ("webhook_verify_token",)),
        ("whatsapp_pii_hmac_key", ("pii_hmac_key",)),
    ],
)
def test_every_class_mints_required_fields(credential_class, required_present):
    broker = _broker()
    creds = broker._mint(credential_class)  # internal resolve, used by both surfaces
    for field in required_present:
        assert (
            field in creds and creds[field]
        ), f"class {credential_class!r} must mint non-empty {field!r}"


# ── mint_secret — the host-PROVIDED-config path (NOT credential-blind) ───────


def test_mint_secret_pii_hmac_key_returns_injected_value():
    broker = _broker(WHATSAPP_PII_HMAC_KEY="the-real-pii-hmac-key")
    # mint_secret returns the secret the connector must USE directly (it needs
    # the key bytes to compute the redaction HMAC) — host-provided config.
    assert broker.mint_secret("whatsapp_pii_hmac_key") == "the-real-pii-hmac-key"


def test_mint_secret_app_secret_returns_injected_value():
    broker = _broker(WHATSAPP_APP_SECRET="the-real-app-secret")
    assert broker.mint_secret("whatsapp_app_secret") == "the-real-app-secret"


def test_mint_secret_telegram_bot_token_returns_injected_value():
    broker = _broker(TELEGRAM_BOT_TOKEN="the-real-tg-token")
    assert broker.mint_secret("telegram_bot_token") == "the-real-tg-token"


# ── Fail-closed: missing required env var raises, never a partial credential ──


def test_missing_required_env_var_raises_missing_credential_error():
    # Drop the smtp password — a required var for the smtp class.
    env = dict(_FULL_ENV)
    del env["EMAIL_SMTP_PASSWORD"]
    broker = CredentialBroker(env=env)
    with pytest.raises(MissingCredentialError) as exc:
        broker._mint("smtp")
    # The error names the missing env var so the operator can act on it.
    assert "EMAIL_SMTP_PASSWORD" in str(exc.value)


def test_empty_required_env_var_is_treated_as_missing():
    broker = _broker(WHATSAPP_PII_HMAC_KEY="")
    with pytest.raises(MissingCredentialError) as exc:
        broker.mint_secret("whatsapp_pii_hmac_key")
    assert "WHATSAPP_PII_HMAC_KEY" in str(exc.value)


def test_bind_transport_missing_required_var_raises_before_build():
    env = dict(_FULL_ENV)
    del env["EMAIL_SMTP_PASSWORD"]
    broker = CredentialBroker(env=env)
    build_called = False

    def build(creds: dict[str, str]) -> _SpyTransport:
        nonlocal build_called
        build_called = True
        return _SpyTransport(creds)

    with pytest.raises(MissingCredentialError):
        broker.bind_transport("smtp", build)
    # Fail-closed: the connector's build() never runs with a partial credential.
    assert build_called is False


def test_optional_env_var_absent_does_not_fail():
    # SLACK_API_BASE_URL is optional; dropping it must NOT raise.
    env = dict(_FULL_ENV)
    del env["SLACK_API_BASE_URL"]
    broker = CredentialBroker(env=env)
    creds = broker._mint("slack_bot_token")
    assert creds["bot_token"] == "xoxb-slack-secret"
    # The optional var is simply absent from the minted creds (no silent "").
    assert "api_base_url" not in creds


# ── Unknown credential class raises a typed error (no silent default) ─────────


def test_unknown_credential_class_raises():
    broker = _broker()
    with pytest.raises(UnknownCredentialClassError) as exc:
        broker._mint("nonexistent_class")
    assert "nonexistent_class" in str(exc.value)


# ── grant() — a scoped view that can mint ONLY the declared classes ──────────


@pytest.mark.asyncio
async def test_grant_allows_declared_class():
    broker = _broker()
    scope = broker.grant(frozenset({"smtp"}))
    handle = scope.bind_transport("smtp", _SpyTransport)
    assert isinstance(handle, BoundTransport)


def test_grant_allows_declared_secret_class():
    broker = _broker()
    scope = broker.grant(frozenset({"whatsapp_pii_hmac_key"}))
    assert scope.mint_secret("whatsapp_pii_hmac_key") == "wa-pii-hmac-key-min-len"


@pytest.mark.asyncio
async def test_grant_blocks_ungranted_class_on_bind_transport():
    broker = _broker()
    scope = broker.grant(frozenset({"smtp"}))
    with pytest.raises(UngrantedCredentialError) as exc:
        scope.bind_transport("imap", _SpyTransport)
    # The error names the ungranted class so the misuse is legible.
    assert "imap" in str(exc.value)


def test_grant_blocks_ungranted_class_on_mint_secret():
    broker = _broker()
    scope = broker.grant(frozenset({"smtp"}))
    with pytest.raises(UngrantedCredentialError):
        scope.mint_secret("whatsapp_pii_hmac_key")


def test_grant_blocks_unknown_class_at_grant_time():
    # Granting a class that does not exist in the registry is a typed error —
    # fail-loud so a typo in requires_credentials never silently grants nothing.
    broker = _broker()
    with pytest.raises(UnknownCredentialClassError):
        broker.grant(frozenset({"smtp", "not_a_real_class"}))


# ── whatsapp mints ALL FOUR secrets across its credential classes ────────────


def test_whatsapp_mints_all_four_secret_classes():
    broker = _broker(
        WHATSAPP_ACCESS_TOKEN="wa-access",
        WHATSAPP_APP_SECRET="wa-app",
        WHATSAPP_WEBHOOK_VERIFY_TOKEN="wa-verify",
        WHATSAPP_PII_HMAC_KEY="wa-pii",
    )
    access = broker._mint("whatsapp_access_token")
    assert access["access_token"] == "wa-access"
    assert access["phone_number_id"] == "1234567890"
    assert access["graph_version"] == "18.0"
    assert broker.mint_secret("whatsapp_app_secret") == "wa-app"
    assert broker.mint_secret("whatsapp_webhook_verify_token") == "wa-verify"
    assert broker.mint_secret("whatsapp_pii_hmac_key") == "wa-pii"


# ── env defaults to os.environ when not injected (NOT exercised against real
#    secrets — only the wiring is asserted) ───────────────────────────────────


def test_default_env_is_os_environ(monkeypatch):
    # When env is not injected, the broker reads os.environ. Set a var there and
    # confirm the broker resolves it — proving the default binding (the test
    # owns + restores the var via monkeypatch, never a real secret).
    monkeypatch.setenv("WHATSAPP_PII_HMAC_KEY", "from-os-environ")
    broker = CredentialBroker()
    assert broker.mint_secret("whatsapp_pii_hmac_key") == "from-os-environ"
