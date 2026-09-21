"""The value report over the API, and the assumption it carries (Phase 6.16)."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config.store import invalidate
from greenlight_ai.db import models

# UTC, not the local clock: a run's ``created_at`` is UTC and the report's bounds are
# UTC days, so a machine in an earlier timezone took `date.today()` to mean yesterday
# every evening and counted none of the runs it had just written.
TODAY = dt.datetime.now(dt.timezone.utc).date()
MONTH_AGO = TODAY - dt.timedelta(days=30)


def _finalized(factory: sessionmaker[Session], order: str, customer: str = "Acme") -> None:
    """A finalized run today, which is what the report counts."""
    with factory() as session:
        session.add(
            models.Run(
                customer_name=customer,
                order_number=order,
                configuration_id="CFG-1",
                status="finalized",
            )
        )
        session.commit()


def test_an_empty_period_reports_nothing_rather_than_failing(client: TestClient, api: str) -> None:
    """A new deployment asking the question gets zero, not an error."""
    response = client.get(f"{api}/admin/value-report?start={MONTH_AGO}&end={TODAY}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["orders"], body["hours_saved"]) == (0, 0)


def test_orders_are_counted_once_however_often_they_were_run(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """The number that makes the report believable."""
    for _ in range(3):
        _finalized(factory, "ORD-1")
    _finalized(factory, "ORD-2")

    body = client.get(f"{api}/admin/value-report?start={MONTH_AGO}&end={TODAY}").json()
    assert body["runs"] == 4
    assert body["orders"] == 2
    assert body["repeat_runs"] == 2
    # Four hours per order by default.
    assert body["hours_saved"] == 8


def test_the_hours_figure_follows_the_console(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """It is the administrator's assumption, and the report carries it."""
    _finalized(factory, "ORD-1")
    saved = client.post(f"{api}/admin/settings", json={"key": "value.hours_per_order", "value": 6})
    assert saved.status_code == 200, saved.text
    invalidate()

    body = client.get(f"{api}/admin/value-report?start={MONTH_AGO}&end={TODAY}").json()
    assert body["hours_per_order"] == 6
    assert body["hours_saved"] == 6


def test_a_backwards_period_is_refused(client: TestClient, api: str) -> None:
    """A typo in the dates should not silently report zero."""
    response = client.get(f"{api}/admin/value-report?start={TODAY}&end={MONTH_AGO}")
    assert response.status_code == 422
    assert "ends before it starts" in response.json()["detail"]
