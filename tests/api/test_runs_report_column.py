"""The verdict, on the row (Phase 6.23e).

Until now the Runs list could only infer *"frozen"* from the status, so the one thing
somebody scanning a month of history wants — did this delivery pass — was a click away
on every row. The verdict comes from the frozen report itself rather than from counting
findings again: the report is the artifact of record, and recomputing beside it is how
two numbers come to disagree.

The other thing pinned here is a shape, not a feature. The verdicts for a page are read
in **one** statement, because the runs list is the busiest read in the product and a
join per row for a column most rows leave empty is how a history screen gets slow as it
fills up.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]


@pytest.fixture()
def frozen(submit: Submit, worker: Worker, client: TestClient, api: str) -> int:
    """A run taken all the way to a frozen report."""
    run_id = int(submit("geography_extra_state").json()["run_id"])
    worker.run_once()
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "false_positive", "review_note": "reviewed by a test"},
        )
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]
    if outstanding:
        client.post(
            f"{api}/runs/{run_id}/coverage/acknowledge",
            json={"targets": outstanding, "note": "seen by a test"},
        )
    frozen = client.post(f"{api}/runs/{run_id}/finalize")
    assert frozen.status_code in (200, 201), frozen.text
    return run_id


def _row(client: TestClient, api: str, run_id: int) -> dict[str, Any]:
    rows = client.get(f"{api}/runs").json()
    return next(row for row in rows if row["id"] == run_id)


def test_a_run_with_no_report_carries_no_verdict(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    """Empty, not "ok" — "no verdict yet" and "it passed" are not near each other."""
    run_id = int(submit().json()["run_id"])
    worker.run_once()
    assert _row(client, api, run_id)["report_verdict"] == ""


def test_a_frozen_run_carries_the_report_s_own_verdict(
    frozen: int, client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """The stored row, not a recount: the report is the artifact of record."""
    row = _row(client, api, frozen)
    assert row["report_verdict"] in {"ok", "not_ok"}
    with factory() as session:
        stored = session.query(models.FinalReport).filter(models.FinalReport.run_id == frozen).one()
        assert row["report_verdict"] == stored.verdict


def test_a_confirmed_finding_makes_it_not_ok(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    """The verdict is the report's, so it follows the decisions a person actually made."""
    run_id = int(submit("score_value_mismatch").json()["run_id"])
    worker.run_once()
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "confirmed", "review_note": "a real problem"},
        )
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]
    if outstanding:
        client.post(
            f"{api}/runs/{run_id}/coverage/acknowledge",
            json={"targets": outstanding, "note": "seen by a test"},
        )
    client.post(f"{api}/runs/{run_id}/finalize")
    assert _row(client, api, run_id)["report_verdict"] == "not_ok"


def test_the_run_detail_agrees_with_the_row(frozen: int, client: TestClient, api: str) -> None:
    """One source, so a person opening the run never sees a different answer."""
    detail = client.get(f"{api}/runs/{frozen}").json()
    assert detail["report_verdict"] == _row(client, api, frozen)["report_verdict"]
    assert detail["finalized"] is True


def test_the_verdicts_are_read_once_for_the_whole_page(
    frozen: int, client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """A column read per row is how a list gets slower the more it has to show."""
    statements: list[str] = []

    def _record(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if "final_reports" in statement:
            statements.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", _record)
    try:
        assert client.get(f"{api}/runs").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert len(statements) == 1, statements
