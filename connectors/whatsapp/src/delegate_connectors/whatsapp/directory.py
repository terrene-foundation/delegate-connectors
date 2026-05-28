# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Principal resolution + unknown-sender disposition.

v0 resolution is an exact-match lookup. Because the shipped ``DelegateIdentity``
validates its ref fields against ``^[a-zA-Z0-9_-]+$`` (and therefore cannot carry
a ``+``-prefixed number), ``authenticate`` resolves by ``delegate_id``; the literal
phone number lives on the message payload. The resolver is ALSO keyed by the
normalized E.164 phone number for the inbound-sender resolution path.

Unknown identities resolve to the closed-enum disposition ``Reject`` (fail-closed,
NOT ``Accept``). ``EscalateToHuman`` is reserved for a later policy shard. This
mirrors the conformance ``BehaviouralOutcome`` enum ``{Accept, Reject,
EscalateToHuman}``. Alias / group resolution is deliberately out of v0 scope.
"""

from __future__ import annotations

import enum

from kailash.delegate.dispatch import Principal

from delegate_connectors.whatsapp.redaction import normalize_e164

__all__ = [
    "UnknownSenderDisposition",
    "ResolutionOutcome",
    "WhatsAppPrincipalResolver",
]


class UnknownSenderDisposition(str, enum.Enum):
    """Closed enum mirroring the conformance ``BehaviouralOutcome``.

    v0 resolves an unknown sender to :attr:`REJECT` (fail-closed).
    :attr:`ESCALATE_TO_HUMAN` is reserved for a later policy shard.
    """

    ACCEPT = "Accept"
    REJECT = "Reject"
    ESCALATE_TO_HUMAN = "EscalateToHuman"


class ResolutionOutcome:
    """Result of resolving an identity: either a Principal or a disposition.

    Exactly one of :attr:`principal` / :attr:`disposition` is meaningful. A
    resolved identity carries a :class:`Principal` and :attr:`disposition` ==
    ``ACCEPT``; an unknown identity carries ``principal is None`` and
    :attr:`disposition` == ``REJECT``.
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


class WhatsAppPrincipalResolver:
    """Dual-keyed resolver of E.164-or-``delegate_id`` → ``Principal`` (v0).

    Construct with a mapping of E.164 phone number → :class:`Principal`. Phone
    numbers are normalized on construction (via :func:`normalize_e164`) so
    :meth:`resolve_phone` lookups are symmetric with incoming ``wa_id``s (both
    pass through the same normalizer).

    The resolver is ALSO keyed by each principal's ``delegate_id`` so
    :meth:`resolve_delegate_id` can resolve a dispatch identity directly —
    required because the shipped ``DelegateIdentity`` cannot carry a phone number
    on its ref fields.
    """

    def __init__(self, principals_by_phone: dict[str, Principal]) -> None:
        if not isinstance(
            principals_by_phone, dict
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "WhatsAppPrincipalResolver requires a dict[str, Principal]; got "
                f"{type(principals_by_phone).__name__}"
            )
        by_phone: dict[str, Principal] = {}
        by_delegate_id: dict[str, Principal] = {}
        for phone, principal in principals_by_phone.items():
            if not isinstance(principal, Principal):
                raise TypeError(
                    f"value for {phone!r} MUST be a Principal; got "
                    f"{type(principal).__name__}"
                )
            by_phone[normalize_e164(phone)] = principal
            by_delegate_id[str(principal.delegate_id)] = principal
        self._by_phone = by_phone
        self._by_delegate_id = by_delegate_id

    def resolve_phone(self, phone: str) -> ResolutionOutcome:
        """Resolve a (possibly surface-formatted) phone number / ``wa_id``.

        Known number → ``ResolutionOutcome(principal, ACCEPT)``. Unknown or
        un-normalizable number → ``ResolutionOutcome(None, REJECT)`` (fail-closed,
        never ``Accept``).
        """
        try:
            normalized = normalize_e164(phone)
        except (TypeError, ValueError):
            return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
        principal = self._by_phone.get(normalized)
        if principal is None:
            return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
        return ResolutionOutcome(principal, UnknownSenderDisposition.ACCEPT)

    def resolve_delegate_id(self, delegate_id: str) -> ResolutionOutcome:
        """Resolve a dispatch identity's ``delegate_id`` to a Principal-or-Reject.

        Known delegate_id → ``ACCEPT`` + Principal. Unknown → ``REJECT``
        (fail-closed). Used by the connector's ``authenticate`` (todo 07) because
        the dispatch identity cannot carry the phone number on its ref fields.
        """
        principal = self._by_delegate_id.get(str(delegate_id))
        if principal is None:
            return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
        return ResolutionOutcome(principal, UnknownSenderDisposition.ACCEPT)
