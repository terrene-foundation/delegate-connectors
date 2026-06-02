# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""The connector-agnostic ``CredentialBroker`` (Phase-0, P0-07).

The host owns ``from_env()``. A connector declares WHICH credential classes it
needs and receives injectable handles — it NEVER reads ``os.environ`` itself.
This module is the host-side surface that resolves those credentials and mints
the handles.

Two minting surfaces, with a deliberate **credential-blindness distinction**
the connector author must understand:

``bind_transport(credential_class, build)`` — the credential-BLIND path
=======================================================================
For SEND tokens (SMTP/IMAP passwords, the Slack/Telegram bot tokens, the
WhatsApp Cloud API access token). The host resolves the secret from its env,
calls the connector-supplied ``build(creds)`` to construct a transport exposing
async ``send`` / ``fetch``, and wraps it in a :class:`BoundTransport`. The
connector receives ONLY the opaque handle — it can call ``send`` / ``fetch``
but can never read ``.config`` / the token, can never ``repr`` the secret, and
can never pickle the handle to dump it. This is the n8n ``getCredentials()``
leak closed by construction (architecture §3.5 layer 2).

``mint_secret(credential_class)`` — the host-PROVIDED-config path
================================================================
For secrets the connector must USE DIRECTLY rather than hand to a transport —
specifically the WhatsApp PII-HMAC key, which the connector needs as key bytes
to compute the redaction HMAC over a phone number. There is no transport to
hide the key behind: the connector computes the HMAC itself. So this surface
returns the secret VALUE. It is NOT credential-blind — it is host-PROVIDED
config (the host still owns ``from_env``; the connector never reads the env),
but the connector does see the bytes because it must. Use ``mint_secret`` ONLY
for the small set of secrets that are genuinely connector-used (the PII-HMAC
key, the webhook verify token, the app secret used for inbound HMAC verify);
use ``bind_transport`` for every outbound SEND token.

Fail-closed
===========
A missing (or empty) required env var for a requested class raises
:class:`MissingCredentialError`. The broker NEVER returns a partial or empty
credential — this reproduces the connectors' existing ``_require_env``
refuse-on-missing behavior at the host boundary.

Scoping
=======
``grant(requires_credentials)`` returns a :class:`ScopedBroker` that can mint
ONLY the declared classes; minting an ungranted class raises
:class:`UngrantedCredentialError`. A connector is handed a scoped broker
matching its declared ``requires_credentials`` so it cannot reach a credential
class it never declared.

Transitional status (NOT-YET-WIRED — P0-11 wires it)
====================================================
This shard BUILDS and TESTS the broker. It does NOT yet wire the reference
connectors to it. The connectors' own transport ``os.environ`` reads
(``email/smtp.py`` / ``imap.py`` ``from_env``, ``slack/web_api.py``,
``telegram/transport.py``, ``whatsapp/cloud_api.py`` / ``webhook.py``
``from_env``) STAY for now — they move to the broker in **P0-11 (Wave 7)**. So
this broker has NO production call site yet: it is a transitional orphan,
accepted per the Phase-0 plan
(``workspaces/connector-platform/todos/active/00-phase0-decoupling-foundation.md``
— P0-11 is the wiring step). The connectors are therefore NOT credential-blind
yet; do not read this module as a claim that they are. The one EXCEPTION landed
in this shard is the WhatsApp redaction per-message ``os.environ`` read, which
is fixed independently (see ``connectors/whatsapp/.../redaction.py``) so that
``mint_secret('whatsapp_pii_hmac_key')`` can feed it in P0-11.

See ``workspaces/connector-platform/02-plans/01-architecture.md`` §3.5 layer 2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Mapping

from delegate_connectors_host.bound_transport import BoundTransport

__all__ = [
    "CredentialBroker",
    "ScopedBroker",
    "CredentialBrokerError",
    "MissingCredentialError",
    "UnknownCredentialClassError",
    "UngrantedCredentialError",
    "CredentialClassSpec",
    "CREDENTIAL_REGISTRY",
    "TransportLike",
    "TransportBuilder",
]


# ── Typed error hierarchy — every failure raises, never returns a default ─────


class CredentialBrokerError(ValueError):
    """Base class for credential-broker failures.

    Subclasses ``ValueError`` so a generic config-load handler still catches
    them, but each concrete subclass below is the canonical typed surface for
    its specific failure mode.
    """


class MissingCredentialError(CredentialBrokerError):
    """A required env var for a requested credential class is unset or empty.

    Fail-closed: the broker refuses to mint a partial credential. The message
    names the missing env var so the operator can act on it — mirrors the
    connectors' existing ``_require_env`` refuse-on-missing shape.
    """


class UnknownCredentialClassError(CredentialBrokerError):
    """A requested credential class is not in :data:`CREDENTIAL_REGISTRY`.

    Fail-loud: a typo in a connector's declared ``requires_credentials`` (or a
    ``mint``/``grant`` call) surfaces here rather than silently granting nothing.
    """


class UngrantedCredentialError(CredentialBrokerError):
    """A :class:`ScopedBroker` was asked to mint a class it was not granted.

    The scope can mint ONLY the classes in its ``requires_credentials`` set;
    any other class raises this typed error.
    """


# ── The registry: credential class -> env vars it resolves ───────────────────


@dataclass(frozen=True, slots=True)
class CredentialClassSpec:
    """Declares the env vars a single credential class resolves.

    ``required`` maps the minted-credential field name -> the env var that
    provides it; EVERY required var must be present and non-empty or the mint
    fails closed. ``optional`` maps field name -> env var for vars that may be
    absent (the field is simply omitted from the minted creds when absent — no
    silent empty-string default).

    ``secret_field`` names the single field :meth:`CredentialBroker.mint_secret`
    returns for a host-PROVIDED-config class (e.g. ``pii_hmac_key``); ``None``
    for transport classes that are minted only via ``bind_transport``.
    """

    required: Mapping[str, str]
    optional: Mapping[str, str] = None  # type: ignore[assignment]
    secret_field: str | None = None

    def __post_init__(self) -> None:
        # Normalize optional to an empty mapping so callers never branch on None.
        if self.optional is None:
            object.__setattr__(self, "optional", {})


# The single source of truth for every credential class the platform's reference
# connectors read today. Re-derived from each connector's transport ``from_env``
# / ``_require_env`` env-var reads. P0-11 moves the connectors onto these specs.
CREDENTIAL_REGISTRY: Mapping[str, CredentialClassSpec] = {
    # email — two distinct transport classes (the connector binds each).
    "smtp": CredentialClassSpec(
        required={
            "host": "EMAIL_SMTP_HOST",
            "port": "EMAIL_SMTP_PORT",
            "user": "EMAIL_SMTP_USER",
            "password": "EMAIL_SMTP_PASSWORD",
        },
        optional={"use_tls": "EMAIL_SMTP_USE_TLS"},
    ),
    "imap": CredentialClassSpec(
        required={
            "host": "EMAIL_IMAP_HOST",
            "port": "EMAIL_IMAP_PORT",
            "user": "EMAIL_IMAP_USER",
            "password": "EMAIL_IMAP_PASSWORD",
        },
        optional={"use_tls": "EMAIL_IMAP_USE_TLS"},
    ),
    # slack — the bot token (send path); API base URL is optional override.
    "slack_bot_token": CredentialClassSpec(
        required={"bot_token": "SLACK_BOT_TOKEN"},
        optional={"api_base_url": "SLACK_API_BASE_URL"},
    ),
    # telegram — the bot token (send path); API base is optional override.
    "telegram_bot_token": CredentialClassSpec(
        required={"bot_token": "TELEGRAM_BOT_TOKEN"},
        optional={"api_base": "TELEGRAM_API_BASE"},
        secret_field="bot_token",
    ),
    # whatsapp — four credential classes.
    # access_token is the Cloud API send credential (transport / bind path);
    # phone_number_id + graph_version are required config that travels with it.
    "whatsapp_access_token": CredentialClassSpec(
        required={
            "access_token": "WHATSAPP_ACCESS_TOKEN",
            "phone_number_id": "WHATSAPP_PHONE_NUMBER_ID",
        },
        optional={"graph_version": "WHATSAPP_GRAPH_VERSION"},
    ),
    # app_secret is used by the connector to verify inbound webhook HMACs — the
    # connector computes the HMAC itself, so this is a host-PROVIDED-config
    # secret (mint_secret), not a transport.
    "whatsapp_app_secret": CredentialClassSpec(
        required={"app_secret": "WHATSAPP_APP_SECRET"},
        secret_field="app_secret",
    ),
    # webhook_verify_token is the GET-challenge token the connector echoes — a
    # host-PROVIDED-config secret the connector uses directly.
    "whatsapp_webhook_verify_token": CredentialClassSpec(
        required={"webhook_verify_token": "WHATSAPP_WEBHOOK_VERIFY_TOKEN"},
        secret_field="webhook_verify_token",
    ),
    # pii_hmac_key is the redaction HMAC key — the connector NEEDS the key bytes
    # to compute the HMAC over a phone number, so this is host-PROVIDED config
    # (mint_secret), NOT credential-blind.
    "whatsapp_pii_hmac_key": CredentialClassSpec(
        required={"pii_hmac_key": "WHATSAPP_PII_HMAC_KEY"},
        secret_field="pii_hmac_key",
    ),
}


# A transport the connector-supplied ``build`` returns: any object exposing
# async ``send`` / ``fetch``. Kept structural so the broker never reaches into
# the transport's internals — it only closure-captures the two methods.
class TransportLike:
    """Structural marker for a transport exposing async ``send`` / ``fetch``.

    Used only for type hints; the broker duck-types on the two methods and never
    isinstance-checks against this class.
    """

    async def send(self, *args: object, **kwargs: object) -> object: ...  # noqa: D102
    async def fetch(self, *args: object, **kwargs: object) -> object: ...  # noqa: D102


# The connector-supplied factory: given the host-minted creds, return a
# transport. The host calls this ONLY after the creds resolved fail-closed, so a
# missing var raises before the connector's build runs.
TransportBuilder = Callable[[Mapping[str, str]], TransportLike]


# ── The broker ───────────────────────────────────────────────────────────────


class CredentialBroker:
    """Host-side credential broker — the connector receives handles, never tokens.

    Parameters
    ----------
    env:
        The environment mapping to resolve credentials from. Defaults to
        ``os.environ`` for production; tests inject a ``dict`` so they never
        touch the real environment (and never need ``monkeypatch.setenv``).
    """

    __slots__ = ("_env",)

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        # os.environ is the default; a dict is injected for tests. We copy into
        # a plain dict so the broker's view is stable for its lifetime even if
        # the caller mutates the passed mapping afterwards.
        self._env: Mapping[str, str] = dict(os.environ if env is None else env)

    # ── credential resolution (fail-closed) ─────────────────────────────────

    def _spec(self, credential_class: str) -> CredentialClassSpec:
        """Resolve a class name to its spec or raise :class:`UnknownCredentialClassError`."""
        spec = CREDENTIAL_REGISTRY.get(credential_class)
        if spec is None:
            raise UnknownCredentialClassError(
                f"unknown credential class {credential_class!r}; registered "
                f"classes are {sorted(CREDENTIAL_REGISTRY)}"
            )
        return spec

    def _mint(self, credential_class: str) -> dict[str, str]:
        """Resolve every required var for ``credential_class`` from the env.

        Fail-closed: a missing OR empty required var raises
        :class:`MissingCredentialError` — the broker NEVER returns a partial
        credential. Optional vars present-and-non-empty are included; absent
        optional vars are omitted (no silent empty-string default).
        """
        spec = self._spec(credential_class)
        creds: dict[str, str] = {}
        for field, env_var in spec.required.items():
            value = self._env.get(env_var)
            if value is None or value == "":
                raise MissingCredentialError(
                    f"{env_var} MUST be set in the environment to mint "
                    f"credential class {credential_class!r} (credentials are "
                    "env-only; the broker refuses a partial credential)"
                )
            creds[field] = value
        for field, env_var in spec.optional.items():
            value = self._env.get(env_var)
            if value is not None and value != "":
                creds[field] = value
        return creds

    # ── the credential-BLIND minting surface ────────────────────────────────

    def bind_transport(
        self,
        credential_class: str,
        build: TransportBuilder,
    ) -> BoundTransport:
        """Mint creds host-side, build the transport, return an opaque handle.

        The host resolves ``credential_class`` from its env (fail-closed), calls
        the connector-supplied ``build(creds)`` to construct a transport exposing
        async ``send`` / ``fetch``, and returns a :class:`BoundTransport` wrapping
        the transport's two methods. The connector receives ONLY the handle — the
        token lives in the transport (closure-captured by the handle's
        ``send`` / ``fetch`` cells) and is never an attribute the connector can
        read.

        Raises :class:`MissingCredentialError` BEFORE calling ``build`` when a
        required var is absent — the connector's build never runs with a partial
        credential.
        """
        creds = self._mint(credential_class)
        transport = build(creds)
        # Close over the live transport so the credential (inside it) is reachable
        # only by CALLING send/fetch, never by reading a handle attribute.
        send = transport.send
        fetch = transport.fetch
        return BoundTransport(send=send, fetch=fetch)

    # ── the host-PROVIDED-config minting surface (NOT credential-blind) ──────

    def mint_secret(self, credential_class: str) -> str:
        """Return a host-provided secret the connector must USE directly.

        For classes whose secret the connector computes WITH (the PII-HMAC key,
        the webhook verify token, the inbound-HMAC app secret). The class MUST
        declare a ``secret_field``; calling ``mint_secret`` on a transport-only
        class raises :class:`UnknownCredentialClassError`-adjacent
        :class:`CredentialBrokerError` (it has no single secret to return).

        Fail-closed identically to ``bind_transport``: a missing/empty required
        var raises :class:`MissingCredentialError`.
        """
        spec = self._spec(credential_class)
        if spec.secret_field is None:
            raise CredentialBrokerError(
                f"credential class {credential_class!r} is a transport class "
                "with no single host-provided secret; use bind_transport(), not "
                "mint_secret()"
            )
        creds = self._mint(credential_class)
        # secret_field is always a required field (validated by _mint above).
        return creds[spec.secret_field]

    # ── scoping ──────────────────────────────────────────────────────────────

    def grant(self, requires_credentials: frozenset[str]) -> "ScopedBroker":
        """Return a scoped view that can mint ONLY the declared classes.

        Every class in ``requires_credentials`` MUST exist in the registry (a
        typo fails loud at grant time via :class:`UnknownCredentialClassError`
        rather than silently granting nothing). The returned
        :class:`ScopedBroker` raises :class:`UngrantedCredentialError` for any
        class outside the granted set.
        """
        for credential_class in requires_credentials:
            self._spec(credential_class)  # fail-loud on unknown at grant time
        return ScopedBroker(self, frozenset(requires_credentials))


class ScopedBroker:
    """A :class:`CredentialBroker` view restricted to a declared class set.

    Handed to a connector matching its ``requires_credentials`` declaration so
    the connector cannot reach a credential class it never declared. Delegates
    every mint to the parent broker AFTER checking the requested class is in the
    granted set.
    """

    __slots__ = ("_broker", "_granted")

    def __init__(self, broker: CredentialBroker, granted: frozenset[str]) -> None:
        self._broker = broker
        self._granted = granted

    @property
    def granted(self) -> frozenset[str]:
        """The credential classes this scope is permitted to mint."""
        return self._granted

    def _check_granted(self, credential_class: str) -> None:
        if credential_class not in self._granted:
            raise UngrantedCredentialError(
                f"credential class {credential_class!r} was not granted to this "
                f"scope; granted classes are {sorted(self._granted)}"
            )

    def bind_transport(
        self,
        credential_class: str,
        build: TransportBuilder,
    ) -> BoundTransport:
        """Scoped :meth:`CredentialBroker.bind_transport` — granted classes only."""
        self._check_granted(credential_class)
        return self._broker.bind_transport(credential_class, build)

    def mint_secret(self, credential_class: str) -> str:
        """Scoped :meth:`CredentialBroker.mint_secret` — granted classes only."""
        self._check_granted(credential_class)
        return self._broker.mint_secret(credential_class)

    def _mint(self, credential_class: str) -> dict[str, str]:
        """Scoped internal mint — granted classes only (used by tests/wiring)."""
        self._check_granted(credential_class)
        return self._broker._mint(credential_class)
