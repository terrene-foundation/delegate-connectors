# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the template + service-window pre-flight Reject gate."""

from __future__ import annotations

import pytest

from delegate_connectors.whatsapp.templates import (
    SERVICE_WINDOW_SECONDS,
    OutsideServiceWindowError,
    ServiceWindowTracker,
    TemplateGate,
    TemplateNotApprovedError,
    WhatsAppRejectError,
)

_RECIPIENT = "+14155550100"
_RECIPIENT_DIGITS = "14155550100"


class _FakeClock:
    """Deterministic injectable clock for window tests (no real sleeping)."""

    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _SpyTransport:
    """Records whether a send was attempted (asserts pre-flight blocked it)."""

    def __init__(self) -> None:
        self.calls = 0

    def send(self, *args, **kwargs) -> None:
        self.calls += 1


def _gate(approved=("order_update",), clock=None):
    tracker = ServiceWindowTracker(now=clock)
    return TemplateGate(approved, tracker), tracker


def test_free_form_outside_window_rejects_and_no_send_attempted():
    clock = _FakeClock()
    gate, _tracker = _gate(clock=clock)
    transport = _SpyTransport()

    with pytest.raises(OutsideServiceWindowError):
        gate.check(_RECIPIENT, template_name=None)
        transport.send(_RECIPIENT)  # unreachable — check() raised first

    assert transport.calls == 0


def test_unapproved_template_rejects_and_no_send_attempted():
    gate, _tracker = _gate(approved=("order_update",))
    transport = _SpyTransport()

    with pytest.raises(TemplateNotApprovedError):
        gate.check(_RECIPIENT, template_name="marketing_blast")
        transport.send(_RECIPIENT)

    assert transport.calls == 0


def test_approved_template_passes_even_with_closed_window():
    clock = _FakeClock()
    gate, _tracker = _gate(approved=("order_update",), clock=clock)
    # No inbound recorded -> window is closed. Approved template is window-exempt.
    gate.check(_RECIPIENT, template_name="order_update")  # must NOT raise


def test_free_form_within_open_window_passes():
    clock = _FakeClock()
    gate, tracker = _gate(clock=clock)
    # Recipient messaged us 1 hour ago -> window open.
    tracker.record_inbound(_RECIPIENT_DIGITS, timestamp=clock.t - 3600)
    gate.check(_RECIPIENT, template_name=None)  # must NOT raise


def test_window_closes_after_24h():
    clock = _FakeClock()
    tracker = ServiceWindowTracker(now=clock)
    tracker.record_inbound(
        _RECIPIENT_DIGITS, timestamp=clock.t - (SERVICE_WINDOW_SECONDS - 60)
    )
    assert tracker.is_window_open(_RECIPIENT_DIGITS) is True
    # Advance past the 24h boundary.
    clock.t += 120
    assert tracker.is_window_open(_RECIPIENT_DIGITS) is False


def test_window_tracker_unknown_recipient_is_closed():
    tracker = ServiceWindowTracker(now=_FakeClock())
    assert tracker.is_window_open("19998887777") is False


def test_record_inbound_defaults_to_now_when_timestamp_absent():
    clock = _FakeClock()
    tracker = ServiceWindowTracker(now=clock)
    tracker.record_inbound(_RECIPIENT_DIGITS, timestamp=None)
    assert tracker.is_window_open(_RECIPIENT_DIGITS) is True


def test_record_inbound_recovers_from_unparseable_timestamp():
    clock = _FakeClock()
    tracker = ServiceWindowTracker(now=clock)
    tracker.record_inbound(_RECIPIENT_DIGITS, timestamp="not-a-number")
    # Falls back to now() rather than raising -> window opens.
    assert tracker.is_window_open(_RECIPIENT_DIGITS) is True


def test_reject_subclasses_share_a_base():
    assert issubclass(OutsideServiceWindowError, WhatsAppRejectError)
    assert issubclass(TemplateNotApprovedError, WhatsAppRejectError)


def test_from_env_value_parses_csv_allowlist():
    tracker = ServiceWindowTracker(now=_FakeClock())
    gate = TemplateGate.from_env_value("order_update, shipping_note ,", tracker)
    assert gate.approved_templates == frozenset({"order_update", "shipping_note"})


def test_window_tracker_keys_are_symmetric_with_inbound_normalization():
    clock = _FakeClock()
    gate, tracker = _gate(clock=clock)
    # Inbound path stores the normalized (bare-digit) key...
    tracker.record_inbound(_RECIPIENT_DIGITS, timestamp=clock.t - 60)
    # ...and a +-prefixed surface-form recipient resolves to the same window.
    gate.check("+1 (415) 555-0100", template_name=None)  # must NOT raise
