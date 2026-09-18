"""Shared fixtures.

Every fixture here is synthetic (ADR-003). The generated case files are built once per
test session into a temporary directory, so the suite never depends on generated files
being committed and a stale fixture can never pass a test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_fixtures  # noqa: E402


@pytest.fixture(scope="session")
def fixtures_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the whole synthetic fixture set once per session.

    Args:
        tmp_path_factory: pytest's session-scoped temp directory factory.

    Returns:
        The fixtures root containing ``cases/`` and ``manifest.json``.
    """
    root = tmp_path_factory.mktemp("fixtures")
    assert generate_fixtures.main(["--out", str(root), "--log-level", "ERROR"]) == 0
    return root


@pytest.fixture(scope="session")
def manifest(fixtures_root: Path) -> dict[str, Any]:
    """The generated manifest, which carries each case's oracle.

    Args:
        fixtures_root: The generated fixtures root.

    Returns:
        The decoded manifest.
    """
    return json.loads((fixtures_root / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def cases(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Manifest entries keyed by case name.

    Args:
        manifest: The decoded manifest.

    Returns:
        Case name to manifest entry.
    """
    return {case["name"]: case for case in manifest["cases"]}
