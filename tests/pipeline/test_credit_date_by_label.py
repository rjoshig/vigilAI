"""Stage 7 reads the labelled credit date and compares it (Phase 6.14b).

Before this, the check searched every sheet name, header and cell for the date's
*value*. It could say "this date appears nowhere" and never "this report says it is cut
as of a different date", and any coincidental occurrence passed it. These tests cover
both halves: the strong comparison where a labelled cell exists, and the fallback that
now says it is a fallback.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from synthetic_model import build_client

from greenlight_ai.pipeline import s7_reports
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import RunGuidance
from greenlight_ai.parsers.base import ReportCell, ReportDocument, ReportSheet


def _report_saying(label: str, value: str) -> ReportDocument:
    """A one-sheet counts report carrying one labelled value.

    Args:
        label: What the delivery calls the field.
        value: The value beside it.

    Returns:
        A parsed report document.
    """
    return ReportDocument(
        path=Path("counts.xlsx"),
        kind="counts",
        sheets=(
            ReportSheet(
                name="Summary",
                header=(),
                rows=(
                    (
                        ReportCell(address="A1", value=label),
                        ReportCell(address="B1", value=value),
                    ),
                ),
            ),
        ),
    )


def _context(credit_date: str, reports: dict[str, ReportDocument], **extra: Any) -> RunContext:
    """A context carrying only what the credit-date check reads.

    Args:
        credit_date: The date the submitter gave, ISO.
        reports: The parsed reports.
        **extra: Anything else to set on the context.

    Returns:
        The context.
    """
    context = RunContext(
        run_id="TEST-CREDIT-DATE",
        osl_path=Path("osl.docx"),
        config_path=Path("config.json"),
        report_paths={},
        client=build_client(),
        guidance=RunGuidance(credit_date=credit_date),
        **extra,
    )
    context.reports = reports  # type: ignore[assignment]
    return context


class TestTheStrongForm:
    """A labelled cell can be disagreed with."""

    def test_a_disagreeing_report_is_a_mismatch_naming_both_dates(self) -> None:
        """The finding the old check could never produce."""
        context = _context("2026-04-30", {"counts": _report_saying("As-of date", "2026-03-31")})
        s7_reports._check_credit_date(context)

        assert len(context.findings) == 1
        finding = context.findings[0]
        assert finding.type == "credit_date_mismatch"
        assert finding.severity == "medium"
        assert "2026-03-31" in finding.title
        assert "2026-04-30" in finding.title
        assert "As-of date" in finding.detail

    def test_an_agreeing_report_produces_nothing(self) -> None:
        """The ordinary case stays silent."""
        context = _context("2026-03-31", {"counts": _report_saying("As-of date", "2026-03-31")})
        s7_reports._check_credit_date(context)
        assert context.findings == []

    def test_the_spelling_of_the_value_does_not_matter(self) -> None:
        """A report writing 03/31/2026 agrees with a submitter writing 2026-03-31."""
        context = _context("2026-03-31", {"counts": _report_saying("Cycle date", "03/31/2026")})
        s7_reports._check_credit_date(context)
        assert context.findings == []

    def test_a_configured_label_is_used(self) -> None:
        """What this delivery calls it, resolved before the run (Phase 6.14b)."""
        context = _context(
            "2026-04-30",
            {"counts": _report_saying("Vintage", "2026-03-31")},
            credit_date_labels=("Vintage",),
        )
        s7_reports._check_credit_date(context)
        assert len(context.findings) == 1
        assert context.findings[0].type == "credit_date_mismatch"


class TestTheFallback:
    """No labelled cell: the old search runs, and says that it did."""

    def test_an_unlabelled_report_falls_back_and_says_so(self) -> None:
        """A weaker answer must never read like a stronger one."""
        context = _context("2026-04-30", {"counts": _report_saying("Delivered count", "1000")})
        s7_reports._check_credit_date(context)

        assert len(context.findings) == 1
        finding = context.findings[0]
        assert finding.type == "credit_date_missing"
        assert "weaker search" in finding.detail

    def test_a_date_present_but_unlabelled_still_passes_the_fallback(self) -> None:
        """Unchanged behaviour where there is nothing better to do."""
        context = _context(
            "2026-03-31", {"counts": _report_saying("Delivered count", "2026-03-31")}
        )
        s7_reports._check_credit_date(context)
        assert context.findings == []

    def test_no_credit_date_given_checks_nothing(self) -> None:
        """A date nobody stated cannot disagree with anything."""
        context = _context("", {"counts": _report_saying("As-of date", "2026-03-31")})
        s7_reports._check_credit_date(context)
        assert context.findings == []


class TestTheDateReaderMirrorsTheWriter:
    """The spellings written out in stage 7 are the ones the comparison reads."""

    def test_every_written_spelling_is_read_back(self) -> None:
        """They are two halves of one fact and drift apart silently otherwise."""
        from greenlight_ai.checks.artifact_match import compare_credit_date

        day = dt.date(2026, 3, 31)
        for spelling in s7_reports._date_spellings(day.isoformat()):
            result = compare_credit_date(day, spelling)
            assert result.kind == "match", f"stage 7 writes {spelling!r} and nothing reads it"
