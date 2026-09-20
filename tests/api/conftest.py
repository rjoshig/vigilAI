"""Fixtures for API and service tests.

Every test runs against its own SQLite file (ADR-017), so the suite needs no Docker and
no Postgres. The worker is driven inline rather than as a process: a test that spawns a
daemon and sleeps is slow and flaky, and the loop is exercised directly instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from synthetic_model import FIXTURE_ALIASES, build_client
from greenlight_ai.api.app import API_PREFIX, create_app
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.llm.settings import LLMSettings
from greenlight_ai.worker.app import Worker


@pytest.fixture()
def db_settings(tmp_path: Path) -> DbSettings:
    """Settings pointing at a fresh SQLite file and data directory."""
    return DbSettings(
        url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        data_dir=tmp_path / "data",
    )


@pytest.fixture()
def factory(db_settings: DbSettings) -> sessionmaker[Session]:
    """A session factory against the test database, with the schema created."""
    engine = create_engine(db_settings)
    create_all(engine)
    return session_factory(engine)


@pytest.fixture()
def client(db_settings: DbSettings, factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """A test client sharing the test database."""
    app = create_app(db_settings)
    app.state.session_factory = factory
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def api() -> str:
    """The API prefix, so tests do not repeat it."""
    return API_PREFIX


@pytest.fixture()
def worker(
    factory: sessionmaker[Session], db_settings: DbSettings, monkeypatch: pytest.MonkeyPatch
) -> Worker:
    """A worker wired to the scripted stand-in model, driven inline by tests."""
    import greenlight_ai.worker.runner as runner

    def _build(settings: Any, cache: Any = None, call_log: Any = None, **_: Any) -> Any:
        return build_client(settings, cache=cache, call_log=call_log)

    monkeypatch.setattr(runner, "build_client", _build)
    return Worker(factory, db_settings.data_dir, is_sqlite=True, llm_settings=LLMSettings())


@pytest.fixture()
def submit(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> Callable[..., Any]:
    """Submit a fixture case through the real multipart endpoint."""

    def _submit(case_name: str = "geography_extra_state", **extra: str) -> Any:
        case = cases[case_name]
        files = [
            (
                "osl",
                (
                    "osl.docx",
                    (fixtures_root / case["osl"]).read_bytes(),
                    "application/octet-stream",
                ),
            ),
            (
                "config",
                ("config.json", (fixtures_root / case["config"]).read_bytes(), "application/json"),
            ),
        ]
        for kind, path in case["reports"].items():
            files.append(
                (
                    kind,
                    (
                        f"{kind}.xlsx",
                        (fixtures_root / path).read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )
            )
        data = {
            "customer_name": case["customer"],
            "order_number": case["order_number"],
            "configuration_id": case["configuration_id"],
            "notes": "submitted by a test",
            **extra,
        }
        return client.post(f"{api}/runs", data=data, files=files)

    return _submit


@pytest.fixture()
def seed_aliases(factory: sessionmaker[Session]) -> None:
    """Load the alias table the synthetic fixtures need."""
    with factory() as session:
        for canonical, aliases in FIXTURE_ALIASES.canonical_by_alias.items():
            session.add(models.AttributeAlias(canonical_name=aliases, alias=canonical))
        session.commit()


@pytest.fixture()
def clear_gate(client: TestClient, api: str) -> Callable[..., None]:
    """Satisfy the finalize gate on a run (ADR-035).

    The gate wants every high and ``review`` finding decided **and** every coverage
    gap and unevaluated check acknowledged. Deciding findings alone no longer opens
    it, so tests that only want a finalized run say so in one call.
    """

    def _clear(
        run_id: int, decision: str = "false_positive", note: str = "reviewed by a test"
    ) -> None:
        for finding in client.get(f"{api}/runs/{run_id}/findings").json():
            if finding["review_status"] == "undecided":
                client.patch(
                    f"{api}/findings/{finding['id']}",
                    json={"review_status": decision, "review_note": note},
                )
        outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]
        if outstanding:
            client.post(
                f"{api}/runs/{run_id}/coverage/acknowledge",
                json={"targets": outstanding, "note": note},
            )

    return _clear
