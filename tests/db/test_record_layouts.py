"""Promoting and borrowing a record layout (Phase 6.22b).

The rule the module promises: a layout is uploaded per run and remembered for the
configuration, promoted at **finalize** and never before. The three things worth
pinning are the ones that go wrong quietly — a layout promoted too early becomes the
baseline a later run is judged against; a borrowed layout re-promoted would claim a
provenance that is not true; and a borrowed layout that does not say so is worse than
no layout at all.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models, record_layouts, versions
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.parsers.record_layout import RecordLayoutDocument, RecordLayoutField

CUSTOMER = "Northwind Credit Union"
CONFIG = "CFG-SYNTH-LAYOUT-18"


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory against a fresh, empty SQLite file."""
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'rl.db'}"))
    create_all(engine)
    return session_factory(engine)


def _rows(*names: str) -> list[dict[str, object]]:
    """A layout snapshot of the named fields."""
    return [
        {"name": name, "data_type": "CHAR", "size": "10", "ordinal": index}
        for index, name in enumerate(names, start=1)
    ]


def _run(
    session: Session,
    *,
    status: str = "needs_review",
    layout: list[dict[str, object]] | None = None,
    borrowed_from: int = 0,
    configuration_id: str = CONFIG,
) -> models.Run:
    """Store a run with a record layout snapshot."""
    run = models.Run(
        customer_name=CUSTOMER,
        order_number="ORD-10018",
        configuration_id=configuration_id,
        status=status,
        record_layout=layout if layout is not None else [],
        record_layout_run_id=borrowed_from,
        finished_at=dt.datetime(2026, 8, 14, 9, 0, tzinfo=dt.timezone.utc),
    )
    session.add(run)
    session.flush()
    return run


class TestPromoting:
    """Finalize is what makes a layout the configuration's."""

    def test_a_finalized_run_promotes_its_layout(self, factory: sessionmaker[Session]) -> None:
        with factory() as session:
            run = _run(session, layout=_rows("SCORE_V3", "ST"))
            row = record_layouts.promote(session, run, "A Reviewer")

            assert row is not None
            assert row.source_run_id == run.id
            assert row.promoted_by == "A Reviewer"
            assert [f["name"] for f in row.fields] == ["SCORE_V3", "ST"]

    def test_a_run_with_no_layout_promotes_nothing(self, factory: sessionmaker[Session]) -> None:
        """The ordinary case. A delivery without a layout leaves the remembered one alone."""
        with factory() as session:
            first = _run(session, layout=_rows("SCORE_V3"))
            record_layouts.promote(session, first, "A Reviewer")

            second = _run(session)
            assert record_layouts.promote(session, second, "A Reviewer") is None

            row = record_layouts.promoted_for(session, CUSTOMER, CONFIG)
            assert row is not None and row.source_run_id == first.id

    def test_a_borrowed_layout_is_never_re_promoted(self, factory: sessionmaker[Session]) -> None:
        """It is already the configuration's.

        Re-promoting would move the source run forward to a run that uploaded nothing,
        and every finding quoting that provenance would be quoting something untrue.
        """
        with factory() as session:
            first = _run(session, layout=_rows("SCORE_V3"))
            record_layouts.promote(session, first, "A Reviewer")

            borrower = _run(session, layout=_rows("SCORE_V3"), borrowed_from=first.id)
            assert record_layouts.promote(session, borrower, "A Reviewer") is None

            row = record_layouts.promoted_for(session, CUSTOMER, CONFIG)
            assert row is not None and row.source_run_id == first.id

    def test_a_run_with_no_configuration_id_promotes_nothing(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The id is what says "the same order again"; without one there is no "again"."""
        with factory() as session:
            run = _run(session, layout=_rows("SCORE_V3"), configuration_id="")
            assert record_layouts.promote(session, run, "A Reviewer") is None

    def test_promoting_again_replaces_the_row_rather_than_adding_one(
        self, factory: sessionmaker[Session]
    ) -> None:
        with factory() as session:
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3")), "A")
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3", "AGE")), "B")

            stored = session.execute(sa.select(models.RecordLayoutRow)).scalars()
            rows = list(stored)
            assert len(rows) == 1
            assert [f["name"] for f in rows[0].fields] == ["SCORE_V3", "AGE"]


class TestTheVersionHistory:
    """A promotion is a definition change, versioned like any other (ADR-029)."""

    def test_each_different_layout_writes_a_version(self, factory: sessionmaker[Session]) -> None:
        with factory() as session:
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3")), "A")
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3", "AGE")), "B")

            listed = versions.list_versions(
                session, "record_layout", versions.record_layout_key(CUSTOMER, CONFIG)
            )
            assert [v.version for v in listed] == [2, 1]

    def test_promoting_the_same_layout_twice_writes_no_second_version(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Otherwise the ten the console lists would fill up with identical entries."""
        with factory() as session:
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3")), "A")
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3")), "B")

            listed = versions.list_versions(
                session, "record_layout", versions.record_layout_key(CUSTOMER, CONFIG)
            )
            assert [v.version for v in listed] == [1]


class TestBorrowing:
    """A run that uploads none gets the configuration's, and is told where it came from."""

    def test_the_uploaded_layout_wins(self, factory: sessionmaker[Session]) -> None:
        with factory() as session:
            record_layouts.promote(session, _run(session, layout=_rows("OLD_FIELD")), "A")
            uploaded = RecordLayoutDocument(fields=(RecordLayoutField("NEW_FIELD"),))

            chosen = record_layouts.run_layout(session, CUSTOMER, CONFIG, uploaded)
            assert chosen.names == ("NEW_FIELD",)
            assert not chosen.borrowed

    def test_a_run_with_none_borrows_and_names_the_run_and_date(
        self, factory: sessionmaker[Session]
    ) -> None:
        with factory() as session:
            source = _run(session, layout=_rows("SCORE_V3", "ST"))
            record_layouts.promote(session, source, "A Reviewer")

            chosen = record_layouts.run_layout(session, CUSTOMER, CONFIG, None)
            assert chosen.names == ("SCORE_V3", "ST")
            assert chosen.borrowed
            assert chosen.provenance == f"from run {source.id} finalized 2026-08-14"

    def test_a_configuration_with_nothing_remembered_gets_an_empty_layout(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The ordinary state, and the one every caller is written to treat as ordinary."""
        with factory() as session:
            chosen = record_layouts.run_layout(session, CUSTOMER, "CFG-NEVER-SEEN", None)
            assert chosen.fields == ()
            assert not chosen.borrowed

    def test_another_customer_does_not_borrow_this_one_s_layout(
        self, factory: sessionmaker[Session]
    ) -> None:
        with factory() as session:
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3")), "A")
            chosen = record_layouts.run_layout(session, "Someone Else", CONFIG, None)
            assert chosen.fields == ()

    def test_an_empty_uploaded_layout_still_falls_back(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A layout with no fields is not a layout, whatever produced it."""
        with factory() as session:
            record_layouts.promote(session, _run(session, layout=_rows("SCORE_V3")), "A")
            chosen = record_layouts.run_layout(session, CUSTOMER, CONFIG, RecordLayoutDocument())
            assert chosen.names == ("SCORE_V3",)
            assert chosen.borrowed


class TestReadingItBack:
    """What a run was checked against, after the fact."""

    def test_a_run_s_own_layout_reads_back_unborrowed(self, factory: sessionmaker[Session]) -> None:
        with factory() as session:
            run = _run(session, layout=_rows("SCORE_V3"))
            read = record_layouts.load_for_run(session, run)
            assert read.names == ("SCORE_V3",)
            assert not read.borrowed

    def test_a_borrowed_layout_reads_back_with_its_provenance(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Stored on the run, so it still reads after the source run is purged."""
        with factory() as session:
            run = _run(session, layout=_rows("SCORE_V3"), borrowed_from=41)
            run.record_layout_source_date = "2026-08-14"
            session.flush()

            read = record_layouts.load_for_run(session, run)
            assert read.provenance == "from run 41 finalized 2026-08-14"
