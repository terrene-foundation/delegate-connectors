# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Refactor-invariant guard for the P0-04 signing-helper extraction.

P0-04 extracted four VERBATIM-duplicated signing-byte helpers
(``build_action_signing_bytes`` / ``build_read_signing_bytes`` /
``verify_action_envelope`` / ``verify_read_receipt``) out of every connector's
``connector.py`` into the single shared module
``delegate_connectors_host.signing_bytes``. Each connector now IMPORTS them.

This test is the structural insurance policy mandated by
``rules/refactor-invariants.md`` MUST Rule 1: it asserts that ZERO DEFINITIONS
of the four helpers remain in any ``connectors/**/connector.py`` (only imports).
Without it, a later parallel-worktree merge from a stale base SHA could silently
re-inline the extracted code (``rules/refactor-invariants.md`` Origin: a 2,103→994
LOC refactor whose missing invariant test let a merge re-inline 1,079 LOC with
zero test failure). The check is AST-based (``ast.FunctionDef`` at module scope),
so it cannot be fooled by the names appearing in import statements, ``__all__``
lists, call sites, or docstrings.

Lives in the default pytest collection path (``host/pyproject.toml::testpaths =
["tests"]``) per ``rules/refactor-invariants.md`` MUST Rule 2 — it runs on every
``pytest`` invocation, not behind an opt-in marker.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# The four helpers extracted into delegate_connectors_host.signing_bytes (P0-04).
# A DEFINITION of any of these inside a connector's connector.py is a re-inline
# regression — the connector must IMPORT them, never re-define them.
_EXTRACTED_HELPERS = frozenset(
    {
        "build_action_signing_bytes",
        "build_read_signing_bytes",
        "verify_action_envelope",
        "verify_read_receipt",
    }
)


def _repo_root() -> Path:
    """Resolve the repo root by walking up from this file until ``connectors/``.

    Robust against the absolute checkout location: walks parents looking for the
    directory that contains the ``connectors/`` tree the invariant guards. Raises
    a typed error (no silent fallback) if the marker directory is never found.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "connectors").is_dir():
            return candidate
    raise RuntimeError(
        "could not resolve repo root: no ancestor of "
        f"{__file__!r} contains a 'connectors/' directory"
    )


def _connector_modules() -> list[Path]:
    """Every ``connectors/**/connector.py`` in the repo (sorted, deterministic)."""
    return sorted((_repo_root() / "connectors").glob("**/connector.py"))


def _helper_definitions(module_path: Path) -> list[str]:
    """Names of the extracted helpers DEFINED (``def``) at module scope in a file.

    AST-based: only ``ast.FunctionDef`` / ``ast.AsyncFunctionDef`` nodes count —
    an ``import`` of the same name, an ``__all__`` entry, or a call site does NOT.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in _EXTRACTED_HELPERS
    ]


def test_at_least_one_connector_module_discovered() -> None:
    """Guard against the glob silently matching nothing (which would pass vacuously)."""
    modules = _connector_modules()
    assert modules, (
        "expected at least one connectors/**/connector.py; the invariant test "
        "would pass vacuously if the glob matched nothing"
    )


@pytest.mark.regression
def test_no_connector_redefines_extracted_signing_helpers() -> None:
    """ZERO definitions of the four extracted helpers remain in any connector.

    The helpers live ONLY in ``delegate_connectors_host.signing_bytes`` after
    P0-04. Any connector that re-defines one of them has re-inlined the extracted
    code — exactly the silent re-inline ``rules/refactor-invariants.md`` guards.
    """
    offenders: dict[str, list[str]] = {}
    for module_path in _connector_modules():
        redefined = _helper_definitions(module_path)
        if redefined:
            offenders[str(module_path)] = redefined

    assert not offenders, (
        "the P0-04 signing-helper extraction was re-inlined — these connector "
        "modules DEFINE helpers that must live only in "
        "delegate_connectors_host.signing_bytes:\n"
        + "\n".join(
            f"  {path}: {', '.join(sorted(names))}"
            for path, names in sorted(offenders.items())
        )
        + "\nReplace each definition with an import from "
        "delegate_connectors_host.signing_bytes (see rules/refactor-invariants.md)."
    )
