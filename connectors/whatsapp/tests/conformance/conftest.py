# Copyright 2026 Terrene Foundation
# SPDX-License-Identifier: Apache-2.0
"""Conformance-tier fixtures. Presence of this conftest.py triggers pytest's
sys.path insertion for ``tests/conformance/`` so the sibling ``loader`` module
is importable without a package wrapper (matches the pattern at
``tests/integration/conftest.py`` for ``_mailpit`` in the email connector)."""
