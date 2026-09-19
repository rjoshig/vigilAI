"""Fixtures for pipeline tests.

The scripted stand-in model lives in ``scripts/synthetic_model.py`` so the golden set
and the test suite drive the pipeline the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from synthetic_model import (  # noqa: F401 - re-exported for tests that import them
    FIXTURE_ALIASES,
    build_client,
    describe_responder,
    extract_responder,
    trace_responder,
)
from greenlight_ai.llm import MockClient
from greenlight_ai.pipeline.context import RunContext


@pytest.fixture()
def client() -> MockClient:
    """A mock client wired with responders for every LLM stage."""
    return build_client()


@pytest.fixture()
def make_context(fixtures_root: Path, cases: dict[str, Any], client: MockClient):
    """Build a run context for a named fixture case."""

    def build(case_name: str) -> RunContext:
        case = cases[case_name]
        return RunContext(
            run_id=f"TEST-{case_name}",
            osl_path=fixtures_root / case["osl"],
            config_path=fixtures_root / case["config"],
            report_paths={
                kind: fixtures_root / path  # type: ignore[misc]
                for kind, path in case["reports"].items()
            },
            client=client,
            customer=case["customer"],
            aliases=FIXTURE_ALIASES,
        )

    return build
