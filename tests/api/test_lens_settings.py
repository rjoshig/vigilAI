"""The lens settings reach the worker (Phase 6.13a, defect D1).

Stage 8's lenses were built in 6.11e and switched by ``LLM_VERIFY_LENSES``. The worker,
though, builds its settings through the console-aware resolver whenever the database
is reachable, and that resolver silently left both lens fields at their defaults. Every
deployment therefore ran with the lenses pinned to ``single``, whatever ``.env`` said,
and nothing failed. These tests hold the resolver to the same contract as the
environment loader.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config.store import invalidate
from greenlight_ai.llm import ConfigError
from greenlight_ai.llm.settings import parse_lenses, resolved_llm_settings


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    invalidate()


def test_lenses_from_the_environment_reach_the_resolved_settings(
    factory: sessionmaker[Session],
) -> None:
    environ = {
        "LLM_VERIFY_LENSES": "delivery,compliance",
        "LLM_MAX_LENS_CALLS_PER_RUN": "7",
    }
    with factory() as session:
        settings = resolved_llm_settings(session, environ)

    assert settings.verify_lenses == ("delivery", "compliance")
    assert settings.max_lens_calls_per_run == 7


def test_the_console_overrides_the_environment_for_lenses(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Console over ``.env`` over default, as for every other setting (ADR-023)."""
    written = client.post(
        f"{api}/admin/settings", json={"key": "llm.verify_lenses", "value": "requirements"}
    )
    assert written.status_code == 200, written.text
    client.post(f"{api}/admin/settings", json={"key": "llm.max_lens_calls_per_run", "value": 3})
    invalidate()

    with factory() as session:
        settings = resolved_llm_settings(session, {"LLM_VERIFY_LENSES": "delivery"})

    assert settings.verify_lenses == ("requirements",)
    assert settings.max_lens_calls_per_run == 3


def test_nothing_configured_is_the_single_second_opinion(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        settings = resolved_llm_settings(session, {})

    assert settings.verify_lenses == ("single",)
    assert settings.max_lens_calls_per_run == 150


@pytest.mark.parametrize("raw", ["single,delivery", "auditor", "delivery,,auditor"])
def test_a_bad_lens_list_is_refused_by_name(raw: str) -> None:
    with pytest.raises(ConfigError, match="llm.verify_lenses"):
        parse_lenses(raw, "llm.verify_lenses")


def test_an_empty_lens_list_switches_verification_off() -> None:
    assert parse_lenses("") == ()
