# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Template + service-window pre-flight Reject gate (load-bearing security).

WhatsApp's Cloud API enforces two outbound rules; the connector enforces them
PRE-FLIGHT (before any side effect / Cloud API call) so a violation surfaces as a
typed ``Reject`` at the connector boundary — NOT a silent send failure (WA-ADR-4):

1. A free-form (non-template) message to a recipient OUTSIDE the open 24-hour
   customer-service window → :class:`OutsideServiceWindowError`.
2. A send naming a template NOT in the connector's approved-template allowlist →
   :class:`TemplateNotApprovedError`.
3. An approved-template send is window-exempt (always allowed regardless of
   window state).

Meta's own error codes are mapped as a backstop only (a later wave); the gate
here is the pre-flight defense. The :class:`ServiceWindowTracker` is fed by the
verified-inbound path (todo 05) via :meth:`ServiceWindowTracker.record_inbound`,
which is the ``window_sink`` callback the webhook ingest calls.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

__all__ = [
    "WhatsAppRejectError",
    "OutsideServiceWindowError",
    "TemplateNotApprovedError",
    "ServiceWindowTracker",
    "TemplateGate",
    "SERVICE_WINDOW_SECONDS",
    "DEFAULT_MAX_WINDOW_ENTRIES",
]

#: The WhatsApp customer-service window: 24 hours from the recipient's last
#: inbound message.
SERVICE_WINDOW_SECONDS = 24 * 60 * 60

#: Default upper bound on the per-recipient last-inbound map. Tuned for a single
#: connector process serving up to ~100k distinct recipients within a rolling
#: 24h window before FIFO-by-record-time eviction begins (L1 security fix —
#: bounds the memory growth surface the Cloud API transport (todo 03) would
#: otherwise expose in production deployments).
DEFAULT_MAX_WINDOW_ENTRIES = 100_000


class WhatsAppRejectError(Exception):
    """Base for pre-flight outbound rejects (the ``Reject`` disposition).

    Both subclasses fire BEFORE any Cloud API call; catching this base catches
    every pre-flight reject.
    """


class OutsideServiceWindowError(WhatsAppRejectError):
    """A free-form send to a recipient whose 24h window is not open."""


class TemplateNotApprovedError(WhatsAppRejectError):
    """A send naming a template not in the approved-template allowlist."""


class ServiceWindowTracker:
    """Per-recipient last-inbound tracker for the 24h customer-service window.

    A bounded-LRU map (``collections.OrderedDict``) of normalized-E.164 →
    last-inbound epoch seconds, fed by the verified-inbound path (todo 05).
    :meth:`is_window_open` reports whether a recipient's window is currently
    open (last inbound within :data:`SERVICE_WINDOW_SECONDS`).

    The map is bounded by ``max_entries`` (default
    :data:`DEFAULT_MAX_WINDOW_ENTRIES`) to cap the memory growth surface the
    Cloud API transport (todo 03) would expose in production. Eviction is
    FIFO-by-record-time: when :meth:`record_inbound` would grow the map past
    the cap, the oldest entry (by most-recent record-time) is removed via
    ``popitem(last=False)`` until the cap holds. Eviction policy invariants:

    1. ``record_inbound`` NEVER grows ``_last_inbound`` beyond ``max_entries``.
    2. ``is_window_open`` is a PURE READ — it does NOT mutate ordering. A
       window-state check is not "activity"; only ``record_inbound`` is.
    3. Eviction is FIFO-by-record-time: the oldest recorded entry evicts first
       when full. Re-recording an existing key moves it to the MRU position
       (so a refreshed key is the LAST to evict, not the first).

    Time source is injectable (``now``) so tests are deterministic without
    sleeping; production uses :func:`time.time`.
    """

    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        max_entries: int = DEFAULT_MAX_WINDOW_ENTRIES,
    ) -> None:
        if not isinstance(max_entries, int) or max_entries <= 0:
            raise ValueError(
                f"ServiceWindowTracker.max_entries MUST be a positive int; "
                f"got {max_entries!r}"
            )
        self._last_inbound: OrderedDict[str, float] = OrderedDict()
        self._now = now or time.time
        self._max_entries = max_entries

    @property
    def size(self) -> int:
        """Current number of recipients tracked (for observability + tests)."""
        return len(self._last_inbound)

    @property
    def max_entries(self) -> int:
        """The upper bound this tracker enforces on tracked recipients."""
        return self._max_entries

    def record_inbound(
        self, normalized_e164: str, timestamp: str | float | None = None
    ) -> None:
        """Record a verified inbound from ``normalized_e164``, opening its window.

        ``timestamp`` is the inbound epoch-seconds (WhatsApp sends a string); when
        absent or unparseable, the current time is used. This is the
        ``window_sink`` callback the webhook ingest invokes (todo 05).

        Bounded by ``max_entries``: re-recording an existing key moves it to
        the MRU position (refresh); recording a new key past the cap evicts
        the oldest-record-time entry via FIFO ``popitem(last=False)`` until
        the cap holds again.
        """
        if not normalized_e164:
            return
        recorded: float
        if timestamp is None or timestamp == "":
            recorded = self._now()
        else:
            try:
                recorded = float(timestamp)
            except (TypeError, ValueError):
                recorded = self._now()
        # Set + move-to-end gives the MRU semantics: refreshing an existing
        # recipient pushes its entry to the back of the eviction queue so it
        # outlives older keys regardless of insertion order.
        self._last_inbound[normalized_e164] = recorded
        self._last_inbound.move_to_end(normalized_e164)
        # Evict FIFO-by-record-time until the cap holds. popitem(last=False)
        # is the LRU eviction primitive on OrderedDict — it removes the entry
        # at the front (oldest record-time after the move_to_end above).
        while len(self._last_inbound) > self._max_entries:
            self._last_inbound.popitem(last=False)

    def is_window_open(self, normalized_e164: str) -> bool:
        """True iff ``normalized_e164`` messaged us within the 24h window.

        PURE READ — does NOT mutate ordering. A window-state check is not
        "activity"; ordering is mutated ONLY by :meth:`record_inbound`. This
        is invariant 2 in the class docstring and is exercised by the
        ``is_window_open does NOT alter eviction order`` regression test.
        """
        last = self._last_inbound.get(normalized_e164)
        if last is None:
            return False
        return (self._now() - last) < SERVICE_WINDOW_SECONDS


class TemplateGate:
    """Pre-flight gate: raises a typed ``Reject`` before any Cloud API send.

    Construct with the approved-template allowlist (typically seeded from
    ``WHATSAPP_APPROVED_TEMPLATES``) and a :class:`ServiceWindowTracker`. The
    connector (todo 07) calls :meth:`check` BEFORE invoking the transport; a
    raised :class:`WhatsAppRejectError` means NO send was attempted.
    """

    def __init__(
        self,
        approved_templates: "set[str] | list[str] | tuple[str, ...]",
        window_tracker: ServiceWindowTracker,
    ) -> None:
        if not isinstance(
            window_tracker, ServiceWindowTracker
        ):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(  # pyright: ignore[reportUnreachable]
                "TemplateGate.window_tracker MUST be a ServiceWindowTracker; got "
                f"{type(window_tracker).__name__}"
            )
        self._approved = {str(t).strip() for t in approved_templates if str(t).strip()}
        self._window = window_tracker

    @classmethod
    def from_env_value(
        cls, approved_templates_csv: str | None, window_tracker: ServiceWindowTracker
    ) -> "TemplateGate":
        """Build from the comma-separated ``WHATSAPP_APPROVED_TEMPLATES`` value."""
        names = (approved_templates_csv or "").split(",")
        return cls(names, window_tracker)

    @property
    def approved_templates(self) -> frozenset[str]:
        return frozenset(self._approved)

    def check(self, recipient_e164: str, *, template_name: str | None = None) -> None:
        """Pre-flight check for an outbound send. Raises a typed ``Reject`` or returns.

        - ``template_name`` set + in the allowlist → window-exempt, returns
          (allowed regardless of window state).
        - ``template_name`` set + NOT in the allowlist →
          :class:`TemplateNotApprovedError`.
        - ``template_name`` ``None`` (free-form) + window open → returns.
        - ``template_name`` ``None`` (free-form) + window closed →
          :class:`OutsideServiceWindowError`.

        ``recipient_e164`` is normalized for the window lookup so it is symmetric
        with the inbound path's stored key (todo 05).
        """
        from delegate_connectors.whatsapp.redaction import normalize_e164

        if template_name is not None:
            if template_name in self._approved:
                return  # approved template — window-exempt
            raise TemplateNotApprovedError(
                f"template {template_name!r} is not in the approved-template allowlist"
            )

        # Free-form: requires an open 24h customer-service window.
        try:
            normalized = normalize_e164(recipient_e164)
        except (TypeError, ValueError):
            normalized = ""
        if not self._window.is_window_open(normalized):
            # The recipient is identified to the caller by redacted token only;
            # never echo the raw number in the reject message.
            raise OutsideServiceWindowError(
                "free-form message rejected: the recipient's 24h customer-service "
                "window is not open (send an approved template instead)"
            )
