# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Production ``KnowledgeLedger`` concrete — durable, append-only audit store.

The host ships this PRODUCTION concrete to replace the in-connector
``InMemoryKnowledgeLedger`` placeholder. It satisfies the SDK
:class:`kailash.delegate.dispatch.KnowledgeLedger` Protocol STRUCTURALLY (the
Protocol is ``@runtime_checkable``; there is NO subclassing — duck typing only).

Backend: an append-only JSONL file. One JSON object per line
(``{"event_type": <str>, "payload": <dict>}``); writes go through
``open(path, "a")`` so a record can only ever EXTEND the file — there is no
truncation, no seek-back, no rewrite path. This is the simplest durable
append-only store that survives process restart: on construction with an
existing file, prior lines are read back into the in-memory snapshot, so a fresh
instance pointed at the same file sees every prior entry.

INVARIANTS (the host contract for this concrete):

- **append-only** — :meth:`record` only appends; there is no public mutation or
  deletion API, and the file is opened in append mode so prior bytes are never
  rewritten.
- **immutable snapshot** — :attr:`records` returns a fresh ``tuple`` of
  ``(event_type, payload)`` pairs whose payloads are deep copies. A caller can
  neither rebind the tuple's slots nor mutate a payload back into stored state.
- **no reference leakage** — payloads are deep-copied on the way IN (so a caller
  mutating its own dict after :meth:`record` cannot alter stored state) and on
  the way OUT (so a caller mutating a snapshot payload cannot alter stored
  state). Combined with append-mode I/O, no path retains a reference that could
  leak a prior entry's contents.
- **NEVER stores credentials** — this store records only ``event_type`` plus a
  non-secret ``payload``. It has no concept of a credential and no path that
  could persist one; the connector boundary is responsible for forwarding ONLY
  non-secret payload (the credential-never-recorded enforcement at that boundary
  is verified separately — see the Phase-0 connector-side shards). This concrete
  simply never introduces a credential of its own and never deep-copies in a way
  that retains a live reference to a caller's object.

An in-memory mode (``path=None``) is provided for tests: records live only in
the snapshot and nothing is written to disk (a sibling instance sees nothing).
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


class DurableKnowledgeLedger:
    """Durable, append-only ``KnowledgeLedger`` concrete (file-backed).

    Args:
        path: Filesystem path to the append-only JSONL backing file. When
            provided, prior entries are loaded into the snapshot on construction
            and every :meth:`record` is durably appended. When ``None`` (the
            default), the ledger runs in non-durable in-memory mode — records
            live only for the lifetime of the instance and nothing is written to
            disk. The in-memory mode exists for tests; production callers pass a
            real path.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path: Path | None = Path(path) if path is not None else None
        # Stored as (event_type, payload) tuples; payloads are deep-copied so the
        # snapshot never shares references with caller-supplied dicts.
        self._records: list[tuple[str, dict[str, Any]]] = []
        if self._path is not None and self._path.exists():
            self._load_existing()

    def _load_existing(self) -> None:
        """Load prior entries from the backing file into the snapshot.

        Each non-empty line is a JSON object with ``event_type`` (str) and
        ``payload`` (dict). A malformed or schema-violating line is a corrupted
        ledger and raises rather than silently dropping audit history — silent
        truncation of an audit store would defeat its purpose.
        """
        assert self._path is not None  # narrowed by the caller
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("event_type"), str)
                    or not isinstance(entry.get("payload"), dict)
                ):
                    raise ValueError(
                        f"corrupt ledger entry at {self._path}:{line_no}: "
                        f"expected {{'event_type': str, 'payload': dict}}"
                    )
                self._records.append((entry["event_type"], entry["payload"]))

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append an event to the ledger — append-only, never mutates prior entries.

        The payload is deep-copied before storage so a caller mutating its own
        dict after this call cannot alter stored state. When the ledger is
        file-backed, the entry is durably appended (``open(path, "a")``) before
        the in-memory snapshot is updated, so a crash between the two leaves the
        durable file as the source of truth on the next construction.

        Args:
            event_type: The audit event kind (e.g. ``"read"`` / ``"write"``).
            payload: A non-secret JSON-serializable mapping. The ledger NEVER
                records credentials; the connector boundary forwards only
                non-secret payload.
        """
        stored = copy.deepcopy(payload)
        if self._path is not None:
            line = json.dumps(
                {"event_type": event_type, "payload": stored},
                separators=(",", ":"),
                sort_keys=True,
            )
            # Append mode: the only write path; prior bytes are never rewritten.
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        self._records.append((event_type, stored))

    @property
    def records(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        """An immutable snapshot of recorded events as a tuple of pairs.

        Returns a fresh ``tuple`` whose payloads are deep copies, so a caller can
        neither rebind a slot nor mutate a payload back into the ledger's stored
        state.
        """
        return tuple(
            (event_type, copy.deepcopy(payload))
            for event_type, payload in self._records
        )
