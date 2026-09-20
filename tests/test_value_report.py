"""What the tool displaced, counted rather than estimated (Phase 6.16).

The number that matters is **distinct orders**, not runs: an order checked three times
displaced one manual check, not three. A report that counted runs would flatter the
figure, and a figure that flatters is one nobody outside the team will believe.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai import value_report
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings

MAY = dt.date(2026, 5, 1)
JUNE = dt.date(2026, 5, 31)


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory against a fresh SQLite file (ADR-017)."""
    engine = create_engine(
        DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'value.db'}", data_dir=tmp_path)
    )
    create_all(engine)
    return session_factory(engine)


def _run(
    session: Session,
    order: str,
    customer: str = "Acme",
    day: int = 10,
    status: str = "finalized",
) -> None:
    """Store one run on a given day of May 2026."""
    session.add(
        models.Run(
            customer_name=customer,
            order_number=order,
            configuration_id="CFG-1",
            status=status,
            created_at=dt.datetime(2026, 5, day, 12, 0, tzinfo=dt.timezone.utc),
        )
    )
    session.flush()


class TestCountingOrders:
    """One order, one manual check displaced, however many times it was run."""

    def test_three_runs_of_one_order_count_once(self, factory: sessionmaker[Session]) -> None:
        """The whole reason this counts orders rather than runs."""
        with factory() as session:
            for _ in range(3):
                _run(session, "ORD-1")
            report = value_report.build(session, MAY, JUNE, hours_per_order=4)

        assert report.runs == 3
        assert report.orders == 1
        assert report.repeat_runs == 2
        assert report.hours_saved == 4

    def test_distinct_orders_each_count(self, factory: sessionmaker[Session]) -> None:
        """The ordinary case."""
        with factory() as session:
            for n in range(5):
                _run(session, f"ORD-{n}")
            report = value_report.build(session, MAY, JUNE, hours_per_order=4)

        assert (report.orders, report.hours_saved, report.repeat_runs) == (5, 20, 0)

    def test_customers_are_counted_for_context(self, factory: sessionmaker[Session]) -> None:
        """Spread matters to a reader: ten orders from one customer is a different story."""
        with factory() as session:
            _run(session, "ORD-1", customer="Acme")
            _run(session, "ORD-2", customer="Northwind")
            report = value_report.build(session, MAY, JUNE, hours_per_order=4)
        assert report.customers == 2


class TestWhatIsNotCounted:
    """Work the tool did not finish has displaced nothing."""

    @pytest.mark.parametrize("status", ["failed", "cancelled", "needs_review", "held", "queued"])
    def test_an_unfinished_run_is_not_counted(
        self, factory: sessionmaker[Session], status: str
    ) -> None:
        """A run still waiting for a reviewer has not replaced a manual check yet."""
        with factory() as session:
            _run(session, "ORD-1", status=status)
            report = value_report.build(session, MAY, JUNE, hours_per_order=4)
        assert (report.runs, report.hours_saved) == (0, 0)

    def test_a_run_outside_the_period_is_not_counted(self, factory: sessionmaker[Session]) -> None:
        """A period means the period."""
        with factory() as session:
            _run(session, "ORD-1", day=10)
            report = value_report.build(
                session, dt.date(2026, 5, 20), dt.date(2026, 5, 25), hours_per_order=4
            )
        assert report.orders == 0

    def test_the_end_date_is_inclusive(self, factory: sessionmaker[Session]) -> None:
        """ "The 1st to the 30th" includes the 30th, or a day's work vanishes."""
        with factory() as session:
            _run(session, "ORD-1", day=31)
            report = value_report.build(session, MAY, JUNE, hours_per_order=4)
        assert report.orders == 1


class TestHowItReads:
    """The figures a reader is actually shown."""

    def test_hours_become_working_weeks(self, factory: sessionmaker[Session]) -> None:
        """A round number of hours means little; weeks of somebody's time means something."""
        with factory() as session:
            for n in range(10):
                _run(session, f"ORD-{n}")
            report = value_report.build(session, MAY, JUNE, hours_per_order=4)
        assert report.hours_saved == 40
        assert report.working_weeks == 1.1

    def test_the_hours_figure_is_carried_so_it_can_be_disagreed_with(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The assumption travels with the number, rather than being hidden in it."""
        with factory() as session:
            _run(session, "ORD-1")
            report = value_report.build(session, MAY, JUNE, hours_per_order=7)
        assert report.hours_per_order == 7
        assert report.hours_saved == 7
