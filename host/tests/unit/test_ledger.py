# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Tier-1 unit tests for the production ``DurableKnowledgeLedger`` concrete.

The host ships the PRODUCTION ``KnowledgeLedger`` concrete that replaces the
in-connector ``InMemoryKnowledgeLedger`` placeholder. The SDK ships
``kailash.delegate.dispatch.KnowledgeLedger`` as a ``@runtime_checkable``
structural Protocol (NO subclassing); these tests assert the concrete satisfies
that Protocol structurally AND holds the append-only / immutable-snapshot /
durable invariants the connector relies on.
"""

from __future__ import annotations

from typing import Any

import pytest

from kailash.delegate.dispatch import KnowledgeLedger as KnowledgeLedgerProtocol

from delegate_connectors_host.ledger import DurableKnowledgeLedger


# --------------------------------------------------------------------------- #
# record() → records snapshot                                                  #
# --------------------------------------------------------------------------- #


def test_record_then_records_snapshot_equals_input_sequence() -> None:
    ledger = DurableKnowledgeLedger()  # in-memory mode (path=None default)
    ledger.record("read", {"message_id": "m1"})
    ledger.record("write", {"action_id": "a1"})

    assert ledger.records == (
        ("read", {"message_id": "m1"}),
        ("write", {"action_id": "a1"}),
    )


def test_records_is_empty_tuple_before_any_record() -> None:
    ledger = DurableKnowledgeLedger()
    assert ledger.records == ()


# --------------------------------------------------------------------------- #
# append-only: second record extends, never replaces; prior entries unchanged  #
# --------------------------------------------------------------------------- #


def test_second_record_extends_never_replaces() -> None:
    ledger = DurableKnowledgeLedger()
    ledger.record("read", {"seq": 1})
    first_snapshot = ledger.records
    ledger.record("read", {"seq": 2})

    # Append-only: the new snapshot is strictly longer and the prior entries
    # are byte-for-byte unchanged at their original positions.
    assert len(ledger.records) == 2
    assert ledger.records[0] == first_snapshot[0]
    assert ledger.records[0] == ("read", {"seq": 1})
    assert ledger.records[1] == ("read", {"seq": 2})


def test_no_public_mutation_or_deletion_api() -> None:
    # The concrete exposes ONLY append-only `record` + the read-only `records`
    # property — no clear/pop/delete/__setitem__ on the public surface.
    ledger = DurableKnowledgeLedger()
    for forbidden in ("clear", "pop", "delete", "remove", "__delitem__", "__setitem__"):
        assert not hasattr(ledger, forbidden), (
            f"DurableKnowledgeLedger must be append-only; found mutation API "
            f"'{forbidden}'"
        )


# --------------------------------------------------------------------------- #
# records returns an immutable tuple snapshot                                   #
# --------------------------------------------------------------------------- #


def test_records_returns_immutable_tuple() -> None:
    ledger = DurableKnowledgeLedger()
    ledger.record("read", {"k": "v"})
    snapshot = ledger.records

    assert isinstance(snapshot, tuple)
    with pytest.raises((TypeError, AttributeError)):
        snapshot[0] = ("write", {})  # type: ignore[index]


def test_mutating_returned_snapshot_does_not_affect_internal_state() -> None:
    ledger = DurableKnowledgeLedger()
    ledger.record("read", {"mutable": "payload"})

    snapshot = ledger.records
    # Mutating a payload dict obtained from the snapshot must NOT leak back into
    # the ledger's stored state (no shared references through the snapshot).
    payload = snapshot[0][1]
    payload["mutable"] = "TAMPERED"

    assert ledger.records[0][1] == {"mutable": "payload"}


def test_mutating_caller_payload_after_record_does_not_affect_ledger() -> None:
    ledger = DurableKnowledgeLedger()
    payload: dict[str, Any] = {"k": "v"}
    ledger.record("read", payload)
    payload["k"] = "TAMPERED"  # caller mutates AFTER recording

    assert ledger.records[0][1] == {"k": "v"}


# --------------------------------------------------------------------------- #
# structural conformance to the SDK KnowledgeLedger Protocol                    #
# --------------------------------------------------------------------------- #


def test_satisfies_sdk_knowledge_ledger_protocol_structurally() -> None:
    ledger = DurableKnowledgeLedger()
    # The SDK exposes the Protocol as @runtime_checkable → isinstance works for
    # the structural conformance check (no subclassing involved).
    assert isinstance(ledger, KnowledgeLedgerProtocol)


def test_record_signature_matches_protocol() -> None:
    import inspect

    sig = inspect.signature(DurableKnowledgeLedger.record)
    params = list(sig.parameters)
    assert params == ["self", "event_type", "payload"]


# --------------------------------------------------------------------------- #
# durability: a NEW instance on the same file sees prior entries                #
# --------------------------------------------------------------------------- #


def test_durable_entries_survive_new_instance_on_same_file(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"

    writer = DurableKnowledgeLedger(path=path)
    writer.record("read", {"message_id": "m1"})
    writer.record("write", {"action_id": "a1", "nested": {"x": 1}})

    # A fresh instance pointed at the same file loads prior entries on construction.
    reader = DurableKnowledgeLedger(path=path)
    assert reader.records == (
        ("read", {"message_id": "m1"}),
        ("write", {"action_id": "a1", "nested": {"x": 1}}),
    )


def test_durable_append_across_instances_is_append_only(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"

    first = DurableKnowledgeLedger(path=path)
    first.record("read", {"seq": 1})

    # Re-open and append: the second instance extends, never truncates.
    second = DurableKnowledgeLedger(path=path)
    second.record("read", {"seq": 2})

    third = DurableKnowledgeLedger(path=path)
    assert third.records == (
        ("read", {"seq": 1}),
        ("read", {"seq": 2}),
    )


def test_construction_on_nonexistent_file_starts_empty(tmp_path) -> None:
    path = tmp_path / "does-not-exist-yet.jsonl"
    ledger = DurableKnowledgeLedger(path=path)
    assert ledger.records == ()
    # First record creates the file durably.
    ledger.record("read", {"k": "v"})
    assert DurableKnowledgeLedger(path=path).records == (("read", {"k": "v"}),)


def test_in_memory_mode_is_not_durable() -> None:
    # path=None → pure in-memory; no file is written and a sibling instance sees
    # nothing (the in-memory mode is the test-only / non-durable variant).
    a = DurableKnowledgeLedger(path=None)
    a.record("read", {"k": "v"})
    b = DurableKnowledgeLedger(path=None)
    assert b.records == ()
