# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the template + service-window pre-flight Reject gate."""

from __future__ import annotations

import pytest

from delegate_connectors.whatsapp.templates import (
    DEFAULT_MAX_WINDOW_ENTRIES,
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


# ---- L1 security fix — bounded LRU on _last_inbound (todo 14) ----------------
# Three invariants (mirroring the class docstring):
#   1. record_inbound NEVER grows _last_inbound beyond max_entries.
#   2. is_window_open is a PURE READ — does NOT mutate ordering.
#   3. Eviction is FIFO-by-record-time; re-recording refreshes to MRU.


def test_record_inbound_caps_at_max_entries_and_evicts_oldest():
    """Invariant 1 + 3: 200 distinct inbounds → size == 100; oldest evicted."""
    clock = _FakeClock()
    tracker = ServiceWindowTracker(now=clock, max_entries=100)
    # Record 200 distinct recipients. Use a synthetic digits-only key per i so
    # the normalization invariant (digits only) is preserved.
    for i in range(200):
        tracker.record_inbound(f"100000000{i:04d}", timestamp=clock.t)
    # Bound holds.
    assert tracker.size == 100
    # Oldest 100 evicted: their keys MUST NOT be in the window.
    for i in range(100):
        assert tracker.is_window_open(f"100000000{i:04d}") is False
    # Newest 100 retained: their keys MUST be in the window.
    for i in range(100, 200):
        assert tracker.is_window_open(f"100000000{i:04d}") is True


def test_is_window_open_is_pure_read_does_not_alter_eviction_order():
    """Invariant 2: is_window_open MUST NOT mutate ordering.

    Record N keys at distinct times, then call is_window_open many times in
    arbitrary order. Adding ONE more inbound past the cap MUST evict the
    structurally-oldest-recorded key, NOT a key whose only "activity" was a
    window-state read.
    """
    clock = _FakeClock()
    tracker = ServiceWindowTracker(now=clock, max_entries=3)
    tracker.record_inbound("11111111111", timestamp=clock.t)  # oldest
    tracker.record_inbound("22222222222", timestamp=clock.t)
    tracker.record_inbound("33333333333", timestamp=clock.t)  # newest

    # Read the oldest key MANY times. If is_window_open mutated ordering, the
    # oldest key would be moved to MRU and the eviction below would target
    # "22222222222" instead — proving the read mutated state.
    for _ in range(100):
        assert tracker.is_window_open("11111111111") is True

    # One more inbound past the cap. Eviction targets the STRUCTURALLY-oldest
    # record-time key, regardless of how many times any key was read.
    tracker.record_inbound("44444444444", timestamp=clock.t)
    assert tracker.size == 3
    assert tracker.is_window_open("11111111111") is False  # evicted (FIFO)
    assert tracker.is_window_open("22222222222") is True
    assert tracker.is_window_open("33333333333") is True
    assert tracker.is_window_open("44444444444") is True


def test_refresh_then_evict_a_key_recorded_again_stays_open_through_the_cap():
    """Acceptance criterion 3: refresh moves the key to MRU.

    A key recorded at t=0, then again at t=10, MUST stay open at
    t=10 + SERVICE_WINDOW_SECONDS - 1 even when the cap is exceeded by
    intervening recipients (refresh moves it to MRU, so it outlives them).
    """
    clock = _FakeClock(t=0.0)
    tracker = ServiceWindowTracker(now=clock, max_entries=3)
    # Record the refreshed key first.
    tracker.record_inbound("99999999999", timestamp=0.0)
    # Two other recipients fill the cap.
    tracker.record_inbound("11111111111", timestamp=1.0)
    tracker.record_inbound("22222222222", timestamp=2.0)
    # Re-record "99999999999" at t=10 — refresh to MRU. Eviction order is now
    # 11111111111 (oldest) < 22222222222 < 99999999999 (most recent).
    tracker.record_inbound("99999999999", timestamp=10.0)
    # A new recipient at t=11 forces eviction. The structurally-oldest entry
    # is "11111111111", NOT "99999999999".
    tracker.record_inbound("33333333333", timestamp=11.0)
    assert tracker.size == 3
    assert tracker.is_window_open("11111111111") is False  # evicted
    # Now advance the clock to just-inside the 24h boundary from the REFRESH
    # time (t=10), and confirm "99999999999" is STILL open.
    clock.t = 10.0 + (SERVICE_WINDOW_SECONDS - 1)
    assert tracker.is_window_open("99999999999") is True


def test_max_entries_must_be_positive_int():
    """Defensive: max_entries=0 / negative / non-int raises ValueError."""
    with pytest.raises(ValueError):
        ServiceWindowTracker(now=_FakeClock(), max_entries=0)
    with pytest.raises(ValueError):
        ServiceWindowTracker(now=_FakeClock(), max_entries=-1)


def test_default_max_entries_is_exposed_and_positive():
    """Sanity: the module-level default is a sensible positive int."""
    assert isinstance(DEFAULT_MAX_WINDOW_ENTRIES, int)
    assert DEFAULT_MAX_WINDOW_ENTRIES > 0
    tracker = ServiceWindowTracker(now=_FakeClock())
    assert tracker.max_entries == DEFAULT_MAX_WINDOW_ENTRIES


def test_size_property_returns_int_count():
    """The size property is the observability surface for the bound."""
    tracker = ServiceWindowTracker(now=_FakeClock(), max_entries=10)
    assert tracker.size == 0
    tracker.record_inbound("11111111111", timestamp=1.0)
    assert tracker.size == 1
    tracker.record_inbound("22222222222", timestamp=2.0)
    assert tracker.size == 2
