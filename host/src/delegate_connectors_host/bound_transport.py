# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""The opaque, non-introspectable ``BoundTransport`` handle (Phase-0, P0-06).

``BoundTransport`` is the host-injected handle a connector receives INSTEAD of a
credential-bearing transport. The host owns ``from_env()`` and the real SMTP /
IMAP transport; it hands the connector ONLY this handle, which exposes ONLY the
brokered side-effect surface (``send`` / ``fetch``). The connector never sees a
raw secret.

Why a new handle type instead of injecting today's transports
=============================================================
Every existing transport leaks its secret through a public ``.config`` property
(``SmtpConfig.password``, etc. — architecture §3.5 layer 2). Injecting those
transports would recreate the exact n8n ``getCredentials()`` leak: a community
node asks the transport for its config and walks away with the decrypted
credential. ``BoundTransport`` closes that vector by construction.

The non-introspectability mechanism
====================================
The credential is **closure-captured**, never an instance attribute:

- The host builds two ``async`` callables (``send`` / ``fetch``) that close over
  the real transport (and therefore the secret) in their cell objects.
- ``BoundTransport`` stores ONLY those two callables, in ``__slots__``. There is
  no instance ``__dict__`` (slots suppress it), so ``vars()`` raises and
  ``handle.__dict__`` is absent — there are no instance-attribute *values* that
  could hold the secret.
- A one-hop ``gc.get_referents(handle)`` walk yields the two callables plus the
  slot/type machinery — but NOT the secret string. The secret lives one hop
  further out, inside each callable's closure cell, which is a referent of the
  *callable*, not of the handle.
- ``__repr__`` redacts: it names the handle and its surface, never the secret.
- Pickling is refused at ``__reduce__`` / ``__reduce_ex__`` / ``__getstate__``,
  so there is no serialization escape that could dump the bound credential.

What this handle does NOT do (later shards)
===========================================
Wiring it to the real SMTP / IMAP transports is the credential broker's job
(P0-07) and the reference-connector refactor (P0-11). This module is the handle
TYPE only: the host constructs it over brokered callables; the connector
consumes ``send`` / ``fetch``.

See ``workspaces/connector-platform/02-plans/01-architecture.md`` §3.5 layer 2.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, SupportsIndex

# A brokered callable is any callable that returns an awaitable. The host's real
# implementations are ``async def`` closures over the live transport; the type is
# kept structural so the handle never reaches into the callable's internals.
BrokeredCallable = Callable[..., Awaitable[Any]]

# Singleton message reused by every pickle-refusal path, so the refusal reason is
# identical and grep-able regardless of which serialization hook the caller hit.
_PICKLE_REFUSED = (
    "BoundTransport is not serializable: it closure-captures brokered "
    "credentials and refuses pickling so the bound secret cannot escape via a "
    "serialized blob. Re-broker the transport host-side instead of pickling the "
    "handle."
)


class BoundTransport:
    """Opaque, credential-blind handle exposing only ``send`` / ``fetch``.

    Construct over two brokered async callables that close over the real
    transport. The handle stores only the callables; the credential is held in
    the callables' closure cells, never as an instance attribute of the handle.

    Parameters
    ----------
    send:
        Brokered async callable performing the outbound side effect. Forwarded
        positional/keyword arguments are passed straight through and the result
        is awaited.
    fetch:
        Brokered async callable performing the inbound side effect, same
        forwarding contract as ``send``.
    """

    # ONLY the brokered callables live here. No config, no password, no token.
    # __slots__ also suppresses the instance __dict__, which is what makes
    # vars()/__dict__ introspection yield nothing to leak.
    __slots__ = ("_send", "_fetch")

    def __init__(self, *, send: BrokeredCallable, fetch: BrokeredCallable) -> None:
        if not callable(send):
            raise TypeError(
                f"BoundTransport 'send' must be a callable returning an awaitable; "
                f"got {type(send).__name__!r}"
            )
        if not callable(fetch):
            raise TypeError(
                f"BoundTransport 'fetch' must be a callable returning an awaitable; "
                f"got {type(fetch).__name__!r}"
            )
        # object.__setattr__ is unnecessary here (no __setattr__ override), but we
        # store the callables directly into the slots. They — and the secret they
        # close over — are reachable only by CALLING them, never by reading an
        # attribute that returns the secret.
        self._send = send
        self._fetch = fetch

    # ------------------------------------------------------------------ #
    # The brokered side-effect surface — the ONLY public methods.
    # ------------------------------------------------------------------ #

    async def send(self, *args: Any, **kwargs: Any) -> Any:
        """Perform the brokered outbound side effect and return its result."""
        return await self._send(*args, **kwargs)

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        """Perform the brokered inbound side effect and return its result."""
        return await self._fetch(*args, **kwargs)

    # ------------------------------------------------------------------ #
    # Credential-redacting representations — never print the secret.
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return "<BoundTransport send/fetch [credentials redacted]>"

    __str__ = __repr__

    # ------------------------------------------------------------------ #
    # Pickle refusal — no serialization escape that dumps the credential.
    #
    # All three of __getstate__, __reduce__, and __reduce_ex__ raise. Python's
    # pickle machinery consults __reduce_ex__ (which by default consults
    # __reduce__ and __getstate__); overriding every entry point closes the
    # cooperative-pickling path that could otherwise reach the slot values.
    # ------------------------------------------------------------------ #

    def __getstate__(self) -> Any:
        raise TypeError(_PICKLE_REFUSED)

    def __setstate__(self, state: Any) -> None:  # pragma: no cover - never reached
        # Symmetric refusal: even a hand-constructed pickle cannot rehydrate one.
        raise TypeError(_PICKLE_REFUSED)

    def __reduce__(self) -> Any:
        raise TypeError(_PICKLE_REFUSED)

    def __reduce_ex__(self, protocol: SupportsIndex) -> Any:
        raise TypeError(_PICKLE_REFUSED)


def bind_transport(
    *, send: BrokeredCallable, fetch: BrokeredCallable
) -> BoundTransport:
    """Factory for :class:`BoundTransport`.

    Mirrors the constructor with a verb-form name for host-side call sites that
    read more naturally as ``bind_transport(send=..., fetch=...)`` when wiring the
    broker. The credential-blindness contract is identical to the constructor's.
    """
    return BoundTransport(send=send, fetch=fetch)


__all__ = ["BoundTransport", "bind_transport", "BrokeredCallable"]
