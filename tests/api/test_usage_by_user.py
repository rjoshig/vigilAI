"""Per-user usage over the API, and the period it is asked for (Phase 6.19)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai import user_usage
from greenlight_ai.db import models


def _run(factory: sessionmaker[Session], status: str, order: str) -> None:
    """A run today, attributed to whoever the placeholder is (ADR-022).

    Args:
        factory: The session factory.
        status: Where it ended up.
        order: The order number.
    """
    with factory() as session:
        user_id = (
            session.execute(models.sa.select(models.User.id).order_by(models.User.id))
            .scalars()
            .first()
        )
        session.add(
            models.Run(
                customer_name="Acme",
                order_number=order,
                configuration_id="CFG-1",
                status=status,
                user_id=user_id,
            )
        )
        session.commit()


def test_an_empty_deployment_answers_rather_than_failing(client: TestClient, api: str) -> None:
    """A console opening the tab on day one gets zero, not an error."""
    body = client.get(f"{api}/admin/usage/by-user").json()

    assert body["users"] == []
    assert body["runs"] == 0
    assert body["days"] == user_usage.DEFAULT_DAYS


def test_it_defaults_to_thirty_days_and_says_which_it_offers(client: TestClient, api: str) -> None:
    """The picker reads its options from the API, so the two cannot drift."""
    body = client.get(f"{api}/admin/usage/by-user").json()

    assert body["days"] == 30
    assert body["periods"] == [7, 30, 90, 180]


def test_every_offered_period_is_accepted(client: TestClient, api: str) -> None:
    """Each option in the picker reaches an answer rather than a 422."""
    for days in user_usage.PERIODS:
        response = client.get(f"{api}/admin/usage/by-user?days={days}")
        assert response.status_code == 200, response.text
        assert response.json()["days"] == days


def test_a_period_nobody_offers_is_refused(client: TestClient, api: str) -> None:
    """The list is closed, so a URL cannot ask for ten years of days."""
    response = client.get(f"{api}/admin/usage/by-user?days=4000")

    assert response.status_code == 422
    assert "7, 30, 90, 180" in response.text


def test_it_counts_the_ways_a_run_went_wrong_apart(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Failed, held and repeated have different causes and different fixes."""
    _run(factory, "finalized", "ORD-1")
    _run(factory, "failed", "ORD-2")
    _run(factory, "held", "ORD-3")
    _run(factory, "finalized", "ORD-1")

    body = client.get(f"{api}/admin/usage/by-user").json()
    row = body["users"][0]

    assert row["runs"] == 4
    assert (row["failed"], row["held"], row["repeat_runs"]) == (1, 1, 1)
    assert row["orders"] == 3
    assert row["failure_rate"] == 0.25
    # The deployment's own average, which is what a person's rate is read against.
    assert body["failure_rate"] == 0.25


def test_a_row_carries_the_account_a_number_would_open(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Clicking a count opens that person's runs, so the id has to be on the row."""
    _run(factory, "finalized", "ORD-1")

    row = client.get(f"{api}/admin/usage/by-user").json()["users"][0]

    assert row["user_id"] > 0
    listed = client.get(f"{api}/runs?submitted_by={row['user_id']}").json()
    assert len(listed) == 1
    assert listed[0]["order_number"] == "ORD-1"
