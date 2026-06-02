# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the opaque, non-introspectable ``BoundTransport`` handle.

``BoundTransport`` is the host-injected handle a connector receives INSTEAD of a
credential-bearing transport. It exposes ONLY the brokered side-effect surface
(``send`` / ``fetch``) and is structurally non-introspectable: walking the
handle's instance attributes / GC referents never yields the raw secret, the
``repr`` redacts it, and the handle refuses to pickle.

These tests construct the handle over DUMMY brokered callables that close over a
fake secret. The credential-bearing transport is closure-captured (held only
inside those callables), NEVER stored as a plain instance attribute. That
closure capture is the mechanism that defeats ``vars()`` / ``__dict__`` /
``gc.get_referents`` introspection: the handle's slots hold only the callables,
and the callables hold the secret in their cell objects — which are NOT instance
attributes of the handle.

Contract under test (architecture §3.5 layer 2, the named n8n ``getCredentials()``
leak the handle exists to close):

- exposes ONLY ``send`` / ``fetch`` (async; delegate to the captured callable)
- NO ``.config`` / ``.password`` / ``.token`` accessor
- credential closure-captured, not an instance attribute
- credential-redacting ``__repr__``
- NOT picklable (``__reduce__`` / ``__reduce_ex__`` / ``__getstate__`` raise)
- credential-blind: the connector receives the handle, never the raw secret
"""

from __future__ import annotations

import gc
import pickle

import pytest

from delegate_connectors_host.bound_transport import BoundTransport

# The fake secret the dummy brokered callables close over. The whole point of
# the handle is that this STRING never escapes via any instance-attribute,
# repr, pickle, or referent-walk path.
FAKE_SECRET = "xoxb-SUPERSECRET"

# A sentinel distinct from any plausible attribute value, so getattr-absence
# checks cannot be satisfied by a falsy real value (e.g. None / "").
_SENTINEL = object()


def _capturing_handle() -> tuple[BoundTransport, dict[str, dict[str, object]]]:
    """Build a BoundTransport over dummy send/fetch closures that capture a secret.

    The closures record that they ran (and the secret they used) into a shared
    ``calls`` dict so tests can assert the brokered side effect executed — while
    the secret itself stays inside the closure cells, never on the handle.
    """
    calls: dict[str, dict[str, object]] = {}
    secret = FAKE_SECRET  # closure-captured by both callables below

    async def broker_send(*args: object, **kwargs: object) -> str:
        # In production this is the host's brokered SMTP send; here it just
        # records that it ran using the captured secret.
        calls["send"] = {"secret_used": secret, "args": args, "kwargs": kwargs}
        return "sent"

    async def broker_fetch(*args: object, **kwargs: object) -> list[str]:
        calls["fetch"] = {"secret_used": secret, "args": args, "kwargs": kwargs}
        return ["msg-1", "msg-2"]

    handle = BoundTransport(send=broker_send, fetch=broker_fetch)
    return handle, calls


# --------------------------------------------------------------------------- #
# 1. send/fetch call through to the captured brokered callables
# --------------------------------------------------------------------------- #


async def test_send_calls_through_to_brokered_callable():
    handle, calls = _capturing_handle()
    result = await handle.send("alice@example.com", subject="hi")
    assert result == "sent"
    # The brokered side effect ran.
    assert "send" in calls
    assert calls["send"]["args"] == ("alice@example.com",)
    assert calls["send"]["kwargs"] == {"subject": "hi"}
    # The closure used the captured secret (this is legitimate — the secret
    # lives in the closure cell, not on the handle).
    assert calls["send"]["secret_used"] == FAKE_SECRET


async def test_fetch_calls_through_to_brokered_callable():
    handle, calls = _capturing_handle()
    result = await handle.fetch(limit=2)
    assert result == ["msg-1", "msg-2"]
    assert "fetch" in calls
    assert calls["fetch"]["kwargs"] == {"limit": 2}
    assert calls["fetch"]["secret_used"] == FAKE_SECRET


async def test_send_is_awaitable_coroutine():
    """``send`` MUST be async and await the captured callable."""
    handle, _ = _capturing_handle()
    coro = handle.send()
    # It is a coroutine that must be awaited (not a sync passthrough).
    import inspect

    assert inspect.iscoroutine(coro)
    await coro  # do not leak an un-awaited coroutine


# --------------------------------------------------------------------------- #
# 2. NO credential / config accessor (the named §3.5 leak)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "attr", ["config", "password", "token", "secret", "credential"]
)
def test_no_credential_accessor(attr):
    """The handle MUST NOT expose a config/credential accessor of any name."""
    handle, _ = _capturing_handle()
    assert getattr(handle, attr, _SENTINEL) is _SENTINEL, (
        f"BoundTransport leaked a '{attr}' accessor — this recreates the n8n "
        f"getCredentials() leak the handle exists to close."
    )


def test_public_surface_is_only_send_and_fetch():
    """Walking the public (non-dunder) surface yields ONLY send + fetch."""
    handle, _ = _capturing_handle()
    public = {name for name in dir(handle) if not name.startswith("_")}
    assert public == {"send", "fetch"}


# --------------------------------------------------------------------------- #
# 3. credential-redacting __repr__
# --------------------------------------------------------------------------- #


def test_repr_does_not_leak_secret():
    handle, _ = _capturing_handle()
    rendered = repr(handle)
    assert FAKE_SECRET not in rendered
    # The repr is still informative (names the handle + its surface) and
    # signals the redaction explicitly.
    assert "BoundTransport" in rendered
    assert "redacted" in rendered.lower()


def test_str_does_not_leak_secret():
    handle, _ = _capturing_handle()
    assert FAKE_SECRET not in str(handle)


# --------------------------------------------------------------------------- #
# 4. NOT picklable — no serialization escape that dumps the bound credential
# --------------------------------------------------------------------------- #


def test_pickle_dumps_raises():
    handle, _ = _capturing_handle()
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(handle)


def test_getstate_raises():
    handle, _ = _capturing_handle()
    with pytest.raises(TypeError):
        handle.__getstate__()


def test_reduce_raises():
    handle, _ = _capturing_handle()
    with pytest.raises(TypeError):
        handle.__reduce__()


def test_reduce_ex_raises():
    handle, _ = _capturing_handle()
    with pytest.raises(TypeError):
        handle.__reduce_ex__(2)


def test_no_pickle_protocol_leaks_the_secret():
    """Across every pickle protocol, dumping MUST fail (never emit the secret)."""
    handle, _ = _capturing_handle()
    for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
        with pytest.raises((TypeError, pickle.PicklingError)):
            pickle.dumps(handle, protocol=protocol)


# --------------------------------------------------------------------------- #
# 5. introspection sweep — the secret is not an instance-attribute value
# --------------------------------------------------------------------------- #


def test_vars_does_not_expose_secret():
    """vars(handle) MUST NOT contain the raw secret as an attribute value.

    With __slots__ holding only the brokered callables, vars()/__dict__ either
    raises (no instance __dict__) or contains only the callables.
    """
    handle, _ = _capturing_handle()
    try:
        instance_vars = vars(handle)
    except TypeError:
        # __slots__ with no __dict__ — there are no instance attribute values
        # to leak at all. This is the strongest form of the guarantee.
        return
    for value in instance_vars.values():
        assert value != FAKE_SECRET
        assert not (isinstance(value, str) and FAKE_SECRET in value)


def test_dict_absent_or_secret_free():
    """__dict__ is either absent (slots) or contains no secret value."""
    handle, _ = _capturing_handle()
    d = getattr(handle, "__dict__", _SENTINEL)
    if d is _SENTINEL:
        return  # __slots__ — no instance __dict__ at all
    assert isinstance(d, dict)
    for value in d.values():
        assert value != FAKE_SECRET
        assert not (isinstance(value, str) and FAKE_SECRET in value)


def test_gc_referents_have_no_secret_string():
    """Direct GC referents of the handle MUST NOT include the raw-secret string.

    The brokered callables ARE legitimate referents; the secret lives inside
    each callable's closure CELL, which is a referent of the *callable*, not of
    the handle. So a one-hop referent walk of the handle yields the callables
    (and the slots/type machinery) but never the bare secret string.
    """
    handle, _ = _capturing_handle()
    referents = gc.get_referents(handle)
    str_referents = [r for r in referents if isinstance(r, str)]
    assert FAKE_SECRET not in str_referents
    # No referent string even CONTAINS the secret as a substring.
    assert all(FAKE_SECRET not in r for r in str_referents)


def test_secret_is_not_a_direct_instance_attribute_value():
    """No attribute reachable by name on the handle returns the raw secret."""
    handle, _ = _capturing_handle()
    for name in dir(handle):
        try:
            value = getattr(handle, name)
        except Exception:
            # Some dunders (e.g. __getstate__) intentionally raise — that is the
            # pickle-refusal contract, not a leak.
            continue
        assert value != FAKE_SECRET, f"attribute '{name}' returned the raw secret"


# --------------------------------------------------------------------------- #
# 6. credential-blindness from the connector's view
# --------------------------------------------------------------------------- #


async def test_connector_view_is_credential_blind():
    """A connector handed the handle can act, but cannot recover the secret.

    This is the end-to-end credential-blindness assertion: the connector uses
    send/fetch (the brokered surface) successfully, yet every introspection path
    it could try fails to surface the secret.
    """
    handle, _ = _capturing_handle()

    # The "connector" can perform its action through the brokered surface.
    assert await handle.send("bob@example.com") == "sent"

    # ...but it cannot recover the credential by any means available to it.
    assert getattr(handle, "config", _SENTINEL) is _SENTINEL
    assert getattr(handle, "password", _SENTINEL) is _SENTINEL
    assert FAKE_SECRET not in repr(handle)
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.dumps(handle)
    referent_strings = [r for r in gc.get_referents(handle) if isinstance(r, str)]
    assert all(FAKE_SECRET not in r for r in referent_strings)


# --------------------------------------------------------------------------- #
# 7. construction validation — both brokered callables required
# --------------------------------------------------------------------------- #


def test_construction_requires_callable_send():
    async def broker_fetch(*_a, **_k):
        return []

    with pytest.raises(TypeError):
        BoundTransport(send="not-callable", fetch=broker_fetch)


def test_construction_requires_callable_fetch():
    async def broker_send(*_a, **_k):
        return "sent"

    with pytest.raises(TypeError):
        BoundTransport(send=broker_send, fetch=object())
