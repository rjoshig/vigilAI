"""The credit date and the informational configuration id (ADR-027)."""

from __future__ import annotations

from typing import Any, Callable

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.pipeline.s7_reports import _date_spellings

Submit = Callable[..., Any]


def test_a_configuration_id_is_required_and_never_unique(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """The run's own id is its identity; the configuration id names the order and repeats."""
    # Required, never unique: the same configuration is run again months later.
    assert submit(configuration_id="").status_code == 422
    second = submit(order_number="ORD-2", configuration_id="SAME", rerun_reason="second")
    third = submit(order_number="ORD-3", configuration_id="SAME", rerun_reason="third")
    assert second.status_code == 201 and third.status_code == 201
    with factory() as session:
        ids = list(session.execute(sa.select(models.Run.id).order_by(models.Run.id)).scalars())
    assert ids == [1, 2]


def test_the_credit_date_is_stored_and_shown(client: TestClient, api: str, submit: Submit) -> None:
    run_id = submit(credit_date="2026-03-31").json()["run_id"]
    assert client.get(f"{api}/runs/{run_id}").json()["credit_date"] == "2026-03-31"


def test_every_common_spelling_of_a_date_is_looked_for() -> None:
    spellings = _date_spellings("2026-03-31")
    for expected in (
        "2026-03-31",
        "03/31/2026",
        "3/31/2026",
        "31/03/2026",
        "20260331",
        "march 31, 2026",
        "31 mar 2026",
        "31-mar-2026",
    ):
        assert expected in spellings, expected


def test_a_credit_date_absent_from_every_artifact_is_a_medium_finding(
    client: TestClient, api: str, factory: sessionmaker[Session], worker: Any, submit: Submit
) -> None:
    """The reports are cut as of a date; a date nobody wrote down is worth a look."""
    assert submit(credit_date="1999-12-31").status_code == 201
    worker.run_once()
    with factory() as session:
        rows = list(
            session.execute(
                sa.select(models.Finding).where(models.Finding.type == "credit_date_missing")
            ).scalars()
        )
    assert len(rows) == 1
    assert rows[0].severity == "medium"
    assert "1999-12-31" in rows[0].title


def test_no_credit_date_means_no_check(
    client: TestClient, api: str, factory: sessionmaker[Session], worker: Any, submit: Submit
) -> None:
    assert submit().status_code == 201
    worker.run_once()
    with factory() as session:
        types = set(session.execute(sa.select(models.Finding.type)).scalars())
    assert "credit_date_missing" not in types
