# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Principal resolution + unknown-sender disposition for Slack.

v0 resolution is an exact-match lookup of a dispatch identity's ``delegate_id``
against a caller-supplied mapping of Slack-id -> ``Principal``. The resolver is
dual-keyed (mirroring email's ``EmailPrincipalResolver``):

- ``by_delegate_id`` is the PRIMARY index — it drives ``authenticate`` (ADR-S2:
  ``delegate_id`` stays the resolution key for cross-connector uniformity and
  stability across handle/workspace changes), and
- ``by_slack_id`` is a SECONDARY literal index — it drives payload attribution
  (resolving the literal Slack id that appears on a message payload).

Slack ids are validated for shape and normalized CASE-SIGNIFICANTLY via
:func:`~delegate_connectors.slack.messages.normalize_slack_id` (NOT lowercased —
the divergence from email). Multi-workspace / team-scoped resolution is deferred;
the team/workspace id lives in ``Principal.claims`` for forward-compat with
multi-workspace OAuth (a later shard) WITHOUT entering the v0 lookup key.

Unknown identities resolve to the closed-enum disposition ``Reject`` (fail-closed,
NEVER ``Accept``); ``EscalateToHuman`` is reserved for a later policy shard. This
mirrors the conformance closed enum ``{Accept, Reject, EscalateToHuman}``.
"""

from __future__ import annotations

import enum

from kailash.delegate.dispatch import Principal

from delegate_connectors.slack.messages import normalize_slack_id

__all__ = [
    "UnknownSenderDisposition",
    "ResolutionOutcome",
    "SlackPrincipalResolver",
]


class UnknownSenderDisposition(str, enum.Enum):
    """Closed enum mirroring the conformance ``BehaviouralOutcome``.

    v0 resolves an unknown identity to :attr:`REJECT` (fail-closed).
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


class SlackPrincipalResolver:
    """Dual-keyed resolver of Slack-id-or-delegate-id -> ``Principal`` (v0).

    Construct with a mapping of Slack id -> :class:`Principal`. Each Slack id is
    shape-validated + normalized CASE-SIGNIFICANTLY on construction (via
    :func:`normalize_slack_id`) so :meth:`resolve_slack_id` lookups are symmetric
    with incoming Slack ids (both pass through the same normalization, neither is
    lowercased).

    The resolver is ALSO keyed by each principal's ``delegate_id`` so
    :meth:`resolve_delegate_id` — the PRIMARY path used by
    ``SlackConnector.authenticate`` — can resolve a dispatch identity directly
    (ADR-S2). ``delegate_id`` is the primary resolution key; the Slack id index
    is a secondary literal index for payload attribution.
    """

    def __init__(self, principals_by_slack_id: dict[str, Principal]) -> None:
        if not isinstance(
            principals_by_slack_id, dict
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "SlackPrincipalResolver requires a dict[str, Principal]; got "
                f"{type(principals_by_slack_id).__name__}"
            )
        by_slack_id: dict[str, Principal] = {}
        by_delegate_id: dict[str, Principal] = {}
        for slack_id, principal in principals_by_slack_id.items():
            if not isinstance(principal, Principal):
                raise TypeError(
                    f"value for {slack_id!r} MUST be a Principal; got "
                    f"{type(principal).__name__}"
                )
            # normalize_slack_id raises SlackFieldError on a malformed key.
            by_slack_id[normalize_slack_id(slack_id)] = principal
            by_delegate_id[str(principal.delegate_id)] = principal
        self._by_slack_id = by_slack_id
        self._by_delegate_id = by_delegate_id

    def resolve_delegate_id(self, delegate_id: str) -> ResolutionOutcome:
        """Resolve a dispatch identity's ``delegate_id`` to a Principal-or-Reject.

        PRIMARY resolution path (drives ``authenticate``). Known delegate_id ->
        ``ACCEPT`` + Principal. Unknown -> ``REJECT`` (fail-closed, NEVER
        ``Accept``).
        """
        principal = self._by_delegate_id.get(str(delegate_id))
        if principal is None:
            return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
        return ResolutionOutcome(principal, UnknownSenderDisposition.ACCEPT)

    def resolve_slack_id(self, slack_id: str) -> ResolutionOutcome:
        """Resolve a literal Slack id to a Principal-or-Reject (secondary index).

        Used for payload attribution (resolving the Slack id that appears on a
        message). The incoming id is normalized case-significantly (NOT
        lowercased), so a mixed-case id round-trips unchanged. Known id ->
        ``ACCEPT`` + Principal. Unknown (or malformed) -> ``REJECT``
        (fail-closed).
        """
        try:
            normalized = normalize_slack_id(slack_id)
        except ValueError:
            # A malformed incoming Slack id is, by construction, not in the
            # index — fail-closed to REJECT rather than propagating the shape
            # error on the attribution path.
            return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
        principal = self._by_slack_id.get(normalized)
        if principal is None:
            return ResolutionOutcome(None, UnknownSenderDisposition.REJECT)
        return ResolutionOutcome(principal, UnknownSenderDisposition.ACCEPT)
