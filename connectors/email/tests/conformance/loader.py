# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Loader for the vendored canonical conformance vector set.

The shipped ``kailash.delegate.conformance.ConformanceVectorLoader.load_canonical()``
raises ``FileNotFoundError`` because the canonical JSON fixture lives in the
``kailash-py`` SOURCE repo only and is not shipped in the PyPI wheel
(``specs/conformance.md`` § The gap). This module loads the vendored copy at
``tests/fixtures/delegate-conformance/canonical.json`` (monorepo root) and
re-hydrates each record into a ``ConformanceVector`` with the proper
``SpecAnchor`` + ``BehaviouralOutcome`` types.

Provenance: the vendored fixture is byte-for-byte from
``terrene-foundation/kailash-py:tests/fixtures/delegate-conformance/canonical.json``
at ref ``main``, fetched under the cross-repo authorization recorded in
``workspaces/email/journal/0012-DECISION-cross-repo-authorized-conformance-fixture-vendoring.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

from kailash.delegate.conformance.schema import (
    BehaviouralOutcome,
    ConformanceVector,
    SpecAnchor,
)

__all__ = [
    "DEFAULT_FIXTURE_PATH",
    "VendoredConformanceLoader",
    "load_canonical_vectors",
]


def _default_fixture_path() -> Path:
    """Resolve the monorepo-root vendored fixture path from this file's location.

    `connectors/email/tests/conformance/loader.py` → ascend four parents to
    the monorepo root, then descend into the vendored fixture directory. The
    resolution is path-based (not import-based) so it survives editable
    installs that place the source tree at an arbitrary checkout location.
    """
    here = Path(__file__).resolve()
    # loader.py -> conformance -> tests -> email -> connectors -> repo root
    repo_root = here.parents[4]
    return repo_root / "tests" / "fixtures" / "delegate-conformance" / "canonical.json"


DEFAULT_FIXTURE_PATH: Path = _default_fixture_path()


class VendoredConformanceLoader:
    """Loads the vendored canonical conformance vector set.

    A thin replacement for ``ConformanceVectorLoader`` (which can't find the
    fixture in a wheel install). Holds no global state.
    """

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE_PATH

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[ConformanceVector]:
        """Load + parse the vendored canonical set into ``ConformanceVector`` instances.

        Raises ``FileNotFoundError`` if the fixture is absent (the same shape
        the shipped loader would raise — but pointed at our vendored path).
        """
        if not self._path.exists():
            raise FileNotFoundError(
                f"vendored canonical conformance fixture not found at {self._path}; "
                "vendor it from terrene-foundation/kailash-py per journal/0012"
            )
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "vectors" not in data:
            raise ValueError(
                f"canonical fixture at {self._path} MUST be a JSON object with a "
                "'vectors' array; got " + type(data).__name__
            )
        vectors: list[ConformanceVector] = []
        for raw in data["vectors"]:
            vectors.append(
                ConformanceVector(
                    id=raw["id"],
                    spec_anchor=SpecAnchor(raw["spec_anchor"]),
                    given=raw["given"],
                    behaviour=raw["behaviour"],
                    expected=BehaviouralOutcome(raw["expected"]),
                )
            )
        return vectors


def load_canonical_vectors(
    fixture_path: Path | None = None,
) -> list[ConformanceVector]:
    """Convenience: load the vendored canonical vectors with default path."""
    return VendoredConformanceLoader(fixture_path).load()
