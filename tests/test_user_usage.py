"""Who is using the tool, and who is having a hard time with it (Phase 6.19)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from greenlight_ai import user_usage
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings

TODAY = dt.date(2026, 9, 20)


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    """An open session against a fresh SQLite file (ADR-017).

    Yields:
        The session, closed when the test ends.
    """
    engine = create_engine(
        DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'usage.db'}", data_dir=tmp_path)
    )
    create_all(engine)
    with session_factory(engine)() as open_session:
        yield open_session


def _at(days_ago: int) -> dt.datetime:
    """A UTC timestamp that many days before `TODAY`.

    Args:
        days_ago: How far back.

    Returns:
        Midday, so a timezone slip in either direction would not change the date.
    """
    return dt.datetime.combine(
        TODAY - dt.timedelta(days=days_ago), dt.time(12, 0), tzinfo=dt.timezone.utc
    )


def _user(session: Session, username: str, name: str = "") -> models.User:
    """An account.

    Args:
        session: An open session.
        username: The sign-in name.
        name: Their display name, when they have one.

    Returns:
        The saved row.
    """
    row = models.User(username=username, name=name, email=f"{username}@example.test")
    session.add(row)
    session.flush()
    return row


def _run(
    session: Session,
    user: models.User,
    *,
    status: str = "finalized",
    order: str = "ORD-1",
    days_ago: int = 0,
    customer: str = "Acme",
) -> models.Run:
    """A run by somebody.

    Args:
        session: An open session.
        user: Who submitted it.
        status: Where it ended up.
        order: The order number, which is what repeats are counted on.
        days_ago: When.
        customer: The customer.

    Returns:
        The saved row.
    """
    row = models.Run(
        customer_name=customer,
        order_number=order,
        configuration_id="CFG-1",
        status=status,
        user_id=user.id,
        created_at=_at(days_ago),
    )
    session.add(row)
    session.flush()
    return row


def test_nobody_has_used_it_yet(session: Session) -> None:
    """A new deployment asking the question gets an empty period, not an error."""
    period = user_usage.build(session, 30, today=TODAY)

    assert period.users == ()
    assert (period.runs, period.failure_rate) == (0, 0.0)
    assert period.days == 30


def test_it_counts_each_person_separately_and_puts_the_busiest_first(session: Session) -> None:
    """The order an administrator reads in is the order the numbers matter."""
    quiet = _user(session, "quiet", "Quiet Person")
    busy = _user(session, "busy", "Busy Person")
    _run(session, quiet, order="ORD-Q")
    for index in range(4):
        _run(session, busy, order=f"ORD-B{index}")
    session.commit()

    period = user_usage.build(session, 30, today=TODAY)

    assert [row.name for row in period.users] == ["Busy Person", "Quiet Person"]
    assert [row.runs for row in period.users] == [4, 1]


def test_the_three_ways_a_run_goes_wrong_are_counted_apart(session: Session) -> None:
    """They have different causes, so a single "problem" count would hide the cause."""
    person = _user(session, "p", "Person")
    _run(session, person, status="finalized", order="ORD-1")
    _run(session, person, status="failed", order="ORD-2")
    _run(session, person, status="held", order="ORD-3")
    _run(session, person, status="finalized", order="ORD-1")  # a second go at ORD-1
    session.commit()

    row = user_usage.build(session, 30, today=TODAY).users[0]

    assert (row.runs, row.failed, row.held) == (4, 1, 1)
    assert (row.orders, row.repeat_runs) == (3, 1)
    assert row.failure_rate == 0.25
    assert row.held_rate == 0.25


def test_a_period_excludes_what_falls_outside_it(session: Session) -> None:
    """Seven days means seven days, counting today."""
    person = _user(session, "p")
    _run(session, person, order="ORD-NEW", days_ago=2)
    _run(session, person, order="ORD-OLD", days_ago=40)
    session.commit()

    assert user_usage.build(session, 7, today=TODAY).users[0].runs == 1
    assert user_usage.build(session, 90, today=TODAY).users[0].runs == 2


def test_the_day_a_period_starts_is_included(session: Session) -> None:
    """An off-by-one here silently drops a day of somebody's work."""
    person = _user(session, "p")
    _run(session, person, days_ago=6)
    session.commit()

    assert user_usage.build(session, 7, today=TODAY).users[0].runs == 1
    assert user_usage.build(session, 6, today=TODAY).users == ()


def test_per_day_is_sparse_rather_than_a_run_of_zeroes(session: Session) -> None:
    """A 180-day period is mostly days nobody submitted anything."""
    person = _user(session, "p")
    _run(session, person, order="ORD-1", days_ago=0)
    _run(session, person, order="ORD-2", days_ago=0)
    _run(session, person, order="ORD-3", days_ago=5)
    session.commit()

    per_day = user_usage.build(session, 30, today=TODAY).users[0].per_day

    assert [(entry.day, entry.count) for entry in per_day] == [
        (TODAY - dt.timedelta(days=5), 1),
        (TODAY, 2),
    ]


def test_a_rate_is_reported_beside_the_deployments_own_average(session: Session) -> None:
    """ "Twice everyone else" is actionable; a score out of a hundred is not."""
    unlucky = _user(session, "unlucky")
    fine = _user(session, "fine")
    _run(session, unlucky, status="failed", order="ORD-1")
    _run(session, unlucky, status="failed", order="ORD-2")
    for index in range(6):
        _run(session, fine, status="finalized", order=f"ORD-F{index}")
    session.commit()

    period = user_usage.build(session, 30, today=TODAY)
    by_name = {row.username: row for row in period.users}

    assert by_name["unlucky"].failure_rate == 1.0
    assert by_name["fine"].failure_rate == 0.0
    assert period.failure_rate == 0.25  # two of eight, across everybody


def test_high_findings_are_averaged_over_runs_that_produced_any(session: Session) -> None:
    """A run that failed produced none, and would otherwise drag the average down."""
    person = _user(session, "p")
    completed = _run(session, person, status="needs_review", order="ORD-1")
    _run(session, person, status="failed", order="ORD-2")
    for index in range(3):
        session.add(
            models.Finding(
                run_id=completed.id,
                finding_id=f"F-{index}",
                type="rule_missing_in_config",
                severity="high",
                title="A requirement is not in the configuration",
            )
        )
    session.commit()

    row = user_usage.build(session, 30, today=TODAY).users[0]

    assert (row.high_findings, row.completed_runs) == (3, 1)
    assert row.high_per_run == 3.0


def test_a_deactivated_account_still_appears(session: Session) -> None:
    """What somebody did does not stop having happened when their account is closed."""
    person = _user(session, "gone", "Gone Person")
    person.is_active = False
    _run(session, person)
    session.commit()

    row = user_usage.build(session, 30, today=TODAY).users[0]

    assert (row.name, row.is_active) == ("Gone Person", False)
