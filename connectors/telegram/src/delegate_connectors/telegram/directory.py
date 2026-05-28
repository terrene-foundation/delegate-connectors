# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Principal resolution + unknown-sender disposition (Telegram, v0).

v0 resolution is a dual-keyed exact-match lookup of a Telegram identity against a
caller-supplied mapping. The resolver is keyed three ways for one ``Principal``:
by stringified integer ``user_id``, by stringified integer ``chat_id``, and by
the ``delegate_id`` view that :meth:`TelegramConnector.authenticate` uses.
Telegram's integer ids are ref-safe — stringified, they pass the shipped
``DelegateIdentity`` ref regex ``^[a-zA-Z0-9_-]+$`` (digits and ``-`` are
allowed), so they can serve as resolution keys directly (see
``workspaces/telegram/journal/0001-DISCOVERY-*``).

A ``@username`` handle is NEVER a resolution key: ``@`` is ref-unsafe AND handles
are mutable, so a supplied handle resolves to the fail-closed disposition
``Reject``. Alias / group-topic resolution is deliberately out of v0 scope.

Unknown identities resolve to the closed-enum disposition ``Reject``
(fail-closed); ``Accept`` is reserved for resolved principals and
``EscalateToHuman`` for a later policy shard. This mirrors the conformance
``BehaviouralOutcome`` enum ``{Accept, Reject, EscalateToHuman}``.
"""

from __future__ import annotations

import enum

from kailash.delegate.dispatch import Principal

__all__ = [
    "UnknownSenderDisposition",
    "ResolutionOutcome",
    "TelegramPrincipalResolver",
]


class UnknownSenderDisposition(str, enum.Enum):
    """Closed enum mirroring the conformance ``BehaviouralOutcome``.

    v0 resolves an unknown sender (and any ``@username`` handle) to
    :attr:`REJECT` (fail-closed). :attr:`ESCALATE_TO_HUMAN` is reserved for a
    later policy shard.
    """

    ACCEPT = "Accept"
    REJECT = "Reject"
    ESCALATE_TO_HUMAN = "EscalateToHuman"


class ResolutionOutcome:
    """Result of resolving an identity: either a Principal or a disposition.

    Exactly one of :attr:`principal` / :attr:`disposition` is meaningful. A
    resolved identity carries a :class:`Principal` and :attr:`disposition` ==
    ``ACCEPT``; an unknown identity (or a ``@username`` handle) carries
    ``principal is None`` and :attr:`disposition` == ``REJECT``.
    """

    __slots__ = ("principal", "disposition")

    def __init__(
        self,
        principal: Principal | None,
        disposition: UnknownSenderDisposition,
    ) -> None:
        self.principal = principal
        self.disposition = disposition

    @property
    def accepted(self) -> bool:
        return self.disposition is UnknownSenderDisposition.ACCEPT


def _stringify_id(raw: int | str) -> str:
    """Normalize a ``user_id`` / ``chat_id`` to its stringified-integer key.

    Accepts an ``int`` or a base-10 integer string (optionally signed) and
    returns the canonical stringified form. A ``bool`` is rejected (it is an
    ``int`` subclass but never a valid Telegram id), as is a non-integer string
    such as a ``@username`` handle — the latter is precisely the ref-unsafe,
    mutable surface that must never become a key.
    """
    if isinstance(raw, bool):
        raise TypeError("Telegram id MUST NOT be a bool")
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str):
        body = raw[1:] if raw[:1] in "+-" else raw
        if body.isdigit() and body != "":
            # Canonicalize so "007" and 7 collide on the same key, and "+7" → "7".
            return str(int(raw))
        raise ValueError(
            "Telegram id key MUST be an integer or a base-10 integer string "
            f"(a @username handle is never a key); got {raw!r}"
        )
    raise TypeError(
        f"Telegram id MUST be an int or str; got {type(raw).__name__}"
    )  # pyright: ignore[reportUnreachable]


class TelegramPrincipalResolver:
    """Dual-keyed resolver of Telegram identity → ``Principal`` (v0).

    Construct with an iterable of ``(user_id, chat_id, principal)`` triples. Each
    principal becomes reachable via THREE symmetric keys:

    * its stringified integer ``user_id`` (:meth:`resolve_user_id`),
    * its stringified integer ``chat_id`` (:meth:`resolve_chat_id`),
    * its ``delegate_id`` (:meth:`resolve_delegate_id`) — the view
      ``authenticate`` uses.

    A ``@username`` handle is never accepted as a registration key or a lookup
    key: :meth:`resolve_handle` always returns a fail-closed ``Reject``, and
    passing a handle to any ``resolve_*`` method raises (handles are ref-unsafe
    and mutable; ``workspaces/telegram/journal/0001-DISCOVERY-*``).
    """

    def __init__(
        self,
        entries: (
            list[tuple[int | str, int | str, Principal]]
            | tuple[tuple[int | str, int | str, Principal], ...]
        ),
    ) -> None:
        by_user_id: dict[str, Principal] = {}
        by_chat_id: dict[str, Principal] = {}
        by_delegate_id: dict[str, Principal] = {}
        for entry in entries:
            try:
                user_id, chat_id, principal = entry
            except (ValueError, TypeError) as exc:
                raise TypeError(
                    "each entry MUST be a (user_id, chat_id, principal) triple; "
                    f"got {entry!r}"
                ) from exc
            if not isinstance(principal, Principal):
                raise TypeError(
                    "the third element of each entry MUST be a Principal; got "
                    f"{type(principal).__name__}"
                )
            by_user_id[_stringify_id(user_id)] = principal
            by_chat_id[_stringify_id(chat_id)] = principal
            by_delegate_id[str(principal.delegate_id)] = principal
        self._by_user_id = by_user_id
        self._by_chat_id = by_chat_id
        self._by_delegate_id = by_delegate_id

    @staticmethod
    def _reject() -> ResolutionOutcome:
        return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)

    @staticmethod
    def _accept(principal: Principal) -> ResolutionOutcome:
        return ResolutionOutcome(principal, UnknownSenderDisposition.ACCEPT)

    def resolve_user_id(self, user_id: int | str) -> ResolutionOutcome:
        """Resolve a Telegram ``user_id`` to a Principal-or-Reject.

        Known ``user_id`` → ``ACCEPT`` + Principal. Unknown → ``REJECT``
        (fail-closed, never ``Accept``). A ``@username`` handle raises rather
        than resolving — a handle is never a key.
        """
        principal = self._by_user_id.get(_stringify_id(user_id))
        return self._accept(principal) if principal is not None else self._reject()

    def resolve_chat_id(self, chat_id: int | str) -> ResolutionOutcome:
        """Resolve a Telegram ``chat_id`` to a Principal-or-Reject.

        Resolves to the SAME ``Principal`` as the paired ``user_id`` (the
        resolver is symmetric across its three keys). Unknown → ``REJECT``.
        """
        principal = self._by_chat_id.get(_stringify_id(chat_id))
        return self._accept(principal) if principal is not None else self._reject()

    def resolve_delegate_id(self, delegate_id: str) -> ResolutionOutcome:
        """Resolve a dispatch identity's ``delegate_id`` to a Principal-or-Reject.

        Known ``delegate_id`` → ``ACCEPT`` + Principal. Unknown → ``REJECT``
        (fail-closed). This is the view ``TelegramConnector.authenticate`` uses.
        """
        principal = self._by_delegate_id.get(str(delegate_id))
        return self._accept(principal) if principal is not None else self._reject()

    def resolve_handle(self, handle: str) -> ResolutionOutcome:
        """Resolve a ``@username`` handle — ALWAYS fail-closed ``Reject``.

        A handle is ref-unsafe (``@`` fails the ``DelegateIdentity`` ref regex)
        AND mutable, so it is never a stable resolution key. This method exists
        so the fail-closed contract is explicit and testable: a supplied handle
        resolves to ``Reject``, never ``Accept`` — even if a numerically-equal
        id is registered.
        """
        del handle  # intentionally unused — the contract is "always Reject" regardless of input
        return self._reject()
