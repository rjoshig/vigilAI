"""What a delivery calls its credit date, and reading it (Phase 6.14b).

The behaviour these protect is the difference between "this date appears somewhere in
some cell" and "this report says it is cut as of a date that is not the one you gave
me". The first can pass on a coincidence and can never report a disagreement; the
second is the check a reviewer actually wants.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.checks import field_labels as fl
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.parsers.base import ReportCell, ReportDocument, ReportSheet


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory against a fresh SQLite file (ADR-017).

    Local to this module: resolution is a database question but not an API one, and
    these tests should not need the API fixtures to run.
    """
    engine = create_engine(
        DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'labels.db'}", data_dir=tmp_path)
    )
    create_all(engine)
    return session_factory(engine)


def _report(rows: list[list[object]], name: str = "Summary") -> ReportDocument:
    """Build a one-sheet report from plain values.

    Args:
        rows: The cell values, row by row.
        name: The sheet name.

    Returns:
        A parsed report document a check can read.
    """
    return ReportDocument(
        path=Path("synthetic.xlsx"),
        kind="counts",
        sheets=(
            ReportSheet(
                name=name,
                header=(),
                rows=tuple(
                    tuple(
                        ReportCell(address=f"{chr(65 + column)}{index + 1}", value=value)
                        for column, value in enumerate(row)
                    )
                    for index, row in enumerate(rows)
                ),
            ),
        ),
    )


class TestNormalising:
    """One configured spelling has to cover the several a report might use."""

    @pytest.mark.parametrize("value", ["As-of date", "as_of  date", "AS OF DATE", "  As of Date. "])
    def test_one_label_covers_its_spellings(self, value: str) -> None:
        """Punctuation, case and spacing are noise in a label."""
        assert fl.normalize_label(value) == "as of date"


class TestFindingTheLabelledValue:
    """Reading the cell beside the label."""

    def test_it_reads_the_next_non_empty_cell_on_the_row(self) -> None:
        """The shape these workbooks use: a label, then its value."""
        reports = {"counts": _report([["Delivered count", 100], ["As-of date", "2026-03-31"]])}
        hit = fl.find_labelled_value(reports, ["as-of date"])
        assert hit is not None
        assert hit.value == "2026-03-31"
        assert hit.label == "As-of date"
        assert hit.source == "counts · Summary!As-of date"

    def test_it_skips_empty_cells_between_the_label_and_the_value(self) -> None:
        """A merged or padded row still answers."""
        reports = {"counts": _report([["Cycle date", None, "", "2026-03-31"]])}
        hit = fl.find_labelled_value(reports, ["cycle date"])
        assert hit is not None and hit.value == "2026-03-31"

    def test_an_unlabelled_report_gives_nothing(self) -> None:
        """Absence is reported as absence, so the caller can fall back and say so."""
        reports = {"counts": _report([["Delivered count", 100]])}
        assert fl.find_labelled_value(reports, ["as-of date"]) is None

    def test_a_label_with_no_value_beside_it_is_not_a_hit(self) -> None:
        """A heading on its own row describes a section, not a value."""
        reports = {"counts": _report([["As-of date"], ["Delivered count", 100]])}
        assert fl.find_labelled_value(reports, ["as-of date"]) is None

    def test_no_labels_configured_finds_nothing_rather_than_everything(self) -> None:
        """An empty label set must not degrade into matching any cell."""
        reports = {"counts": _report([["As-of date", "2026-03-31"]])}
        assert fl.find_labelled_value(reports, []) is None


class TestResolvingLabels:
    """Scope precedence, and the built-ins that are always there."""

    def test_the_built_ins_are_present_with_nothing_configured(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Configuring nothing must never make the check worse than it was."""
        with factory() as session:
            labels = fl.resolve_labels(session, fl.CREDIT_DATE)
        assert "as-of date" in labels
        assert "credit date" in labels

    def test_a_configured_label_is_tried_before_the_built_ins(
        self, factory: sessionmaker[Session]
    ) -> None:
        """What this delivery calls it beats what deliveries generally call it."""
        with factory() as session:
            session.add(
                models.FieldLabel(canonical=fl.CREDIT_DATE, label="Vintage", scope="everywhere")
            )
            session.commit()
            labels = fl.resolve_labels(session, fl.CREDIT_DATE)
        assert labels[0] == "Vintage"

    def test_a_programme_label_does_not_leak_to_other_programmes(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The whole point of scoping it (ADR-029)."""
        with factory() as session:
            session.add(
                models.FieldLabel(
                    canonical=fl.CREDIT_DATE, label="Solicitation date", scope="programme:AS"
                )
            )
            session.commit()
            inside = fl.resolve_labels(session, fl.CREDIT_DATE, programme="AS")
            outside = fl.resolve_labels(session, fl.CREDIT_DATE, programme="AM")
        assert "Solicitation date" in inside
        assert "Solicitation date" not in outside

    def test_an_inactive_label_is_not_resolved(self, factory: sessionmaker[Session]) -> None:
        """Switching one off is how a wrong label is retired without losing the row."""
        with factory() as session:
            session.add(
                models.FieldLabel(
                    canonical=fl.CREDIT_DATE,
                    label="Vintage",
                    scope="everywhere",
                    is_active=False,
                )
            )
            session.commit()
            labels = fl.resolve_labels(session, fl.CREDIT_DATE)
        assert "Vintage" not in labels
