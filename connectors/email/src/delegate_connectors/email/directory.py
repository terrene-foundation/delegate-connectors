# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Principal resolution + unknown-sender disposition.

v0 resolution is an exact-match lookup of a NORMALIZED email address against a
caller-supplied mapping of address → :class:`~kailash.delegate.dispatch.Principal`.
Alias / domain-rule resolution is deliberately out of v0 scope.

Unknown senders resolve to the closed-enum disposition ``Reject`` (fail-closed);
``Accept`` is reserved for resolved principals and ``EscalateToHuman`` for a
later policy shard. This mirrors the conformance ``BehaviouralOutcome`` enum
``{Accept, Reject, EscalateToHuman}``.
"""

from __future__ import annotations

import enum
from email.utils import parseaddr

from kailash.delegate.dispatch import Principal

__all__ = [
    "UnknownSenderDisposition",
    "ResolutionOutcome",
    "EmailPrincipalResolver",
    "normalize_address",
]


class UnknownSenderDisposition(str, enum.Enum):
    """Closed enum mirroring the conformance ``BehaviouralOutcome``.

    v0 resolves an unknown sender to :attr:`REJECT` (fail-closed).
    :attr:`ESCALATE_TO_HUMAN` is reserved for a later policy shard.
    """

    ACCEPT = "Accept"
    REJECT = "Reject"
    ESCALATE_TO_HUMAN = "EscalateToHuman"


def normalize_address(address: str) -> str:
    """Normalize an email address for exact-match resolution.

    Strips any RFC-5322 display name (``Foo <a@b.com>`` → ``a@b.com``),
    lowercases, and trims surrounding whitespace. Applied IDENTICALLY to both
    stored directory keys and incoming addresses so resolution is symmetric.
    """
    if not isinstance(address, str):
        raise TypeError(
            f"normalize_address requires a str; got {type(address).__name__}"
        )
    addr_spec = parseaddr(address)[1] or address
    return addr_spec.strip().lower()


class ResolutionOutcome:
    """Result of resolving an address: either a Principal or a disposition.

    Exactly one of :attr:`principal` / :attr:`disposition` is meaningful.
    A resolved address carries a :class:`Principal` and
    :attr:`disposition` == ``ACCEPT``; an unknown address carries
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


class EmailPrincipalResolver:
    """Exact-match resolver of normalized email address → ``Principal`` (v0).

    Construct with a mapping of address → :class:`Principal`. Addresses are
    normalized on construction so lookups are symmetric with incoming
    addresses (both pass through :func:`normalize_address`).
    """

    def __init__(self, principals_by_address: dict[str, Principal]) -> None:
        if not isinstance(principals_by_address, dict):
            raise TypeError(
                "EmailPrincipalResolver requires a dict[str, Principal]; got "
                f"{type(principals_by_address).__name__}"
            )
        normalized: dict[str, Principal] = {}
        for addr, principal in principals_by_address.items():
            if not isinstance(principal, Principal):
                raise TypeError(
                    f"value for {addr!r} MUST be a Principal; got "
                    f"{type(principal).__name__}"
                )
            normalized[normalize_address(addr)] = principal
        self._by_address = normalized

    def resolve(self, address: str) -> ResolutionOutcome:
        """Resolve a (possibly display-named) address to a Principal-or-Reject.

        Known address → ``ResolutionOutcome(principal, ACCEPT)``.
        Unknown address → ``ResolutionOutcome(None, REJECT)`` (fail-closed,
        never ``Accept``).
        """
        normalized = normalize_address(address)
        principal = self._by_address.get(normalized)
        if principal is None:
            return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
        return ResolutionOutcome(principal, UnknownSenderDisposition.ACCEPT)
