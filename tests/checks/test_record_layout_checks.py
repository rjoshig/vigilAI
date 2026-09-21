"""What the record layout lets the tool assert, and how loudly (Phase 6.22e).

One rule under test above all others, and it is acceptance criterion 9: an attribute the
order asked for and the delivery does not carry produces **one** finding, not two. There
are two artifacts that say what shipped — the DIRT reports on it, the record layout
declares it — and a reviewer told the same thing twice learns to read neither line.

What the layout adds is the case the DIRT cannot show: a field the delivered file ships
that nothing measured.
"""

from __future__ import annotations

from pathlib import Path

from greenlight_ai.checks.reports import run_derived_check
from greenlight_ai.parsers.base import ReportCell, ReportDocument, ReportKind, ReportSheet
from greenlight_ai.parsers.record_layout import RecordLayoutDocument, RecordLayoutField
from greenlight_ai.rules.derive import DerivedCheck


def _dirt(*attributes: str) -> dict[ReportKind, ReportDocument]:
    """A DIRT whose attribute sheet reports on the named attributes."""
    rows = tuple(
        (
            ReportCell(address=f"A{index}", value=name),
            ReportCell(address=f"B{index}", value=0),
            ReportCell(address=f"C{index}", value=100),
        )
        for index, name in enumerate(attributes, start=2)
    )
    sheet = ReportSheet(name="Attributes", header=("Attribute", "Min", "Max"), rows=rows)
    return {"dirt": ReportDocument(path=Path("dirt.xlsx"), kind="dirt", sheets=(sheet,))}


def _layout(*names: str, borrowed_from: int = 0, on: str = "") -> RecordLayoutDocument:
    """A record layout declaring the named fields."""
    return RecordLayoutDocument(
        fields=tuple(
            RecordLayoutField(name, "CHAR", "10", index) for index, name in enumerate(names, 1)
        ),
        source_run_id=borrowed_from,
        source_date=on,
    )


def _check(*wanted: str) -> DerivedCheck:
    """A ``fields_present`` check over the named attributes."""
    return DerivedCheck(
        kind="fields_present",
        population="accepts",
        values=wanted,
        rule_id="R-001",
        description=f"{len(wanted)} requested attributes must be present",
    )


class TestOneAlarmBetweenThem:
    """Acceptance criterion 9."""

    def test_an_attribute_in_neither_artifact_is_one_failure(self) -> None:
        outcome = run_derived_check(
            _check("AT01", "GONE"), _dirt("AT01"), record_layout=_layout("AT01")
        )
        assert outcome.passed is False
        assert outcome.detail.count("GONE") == 1
        assert "does not declare them either" in outcome.detail

    def test_everything_present_in_both_passes_and_says_so(self) -> None:
        outcome = run_derived_check(
            _check("AT01", "ST"), _dirt("AT01", "ST"), record_layout=_layout("AT01", "ST")
        )
        assert outcome.passed is True
        assert "record layout" in outcome.detail

    def test_the_observed_figure_names_both_artifacts(self) -> None:
        outcome = run_derived_check(
            _check("AT01"), _dirt("AT01"), record_layout=_layout("AT01", "EXTRA")
        )
        assert outcome.observed == "1 attributes in the DIRT, 2 in the record layout"


class TestWhatTheLayoutAdds:
    """The case the DIRT on its own cannot show."""

    def test_a_field_the_layout_declares_and_the_dirt_never_measured_fails(self) -> None:
        """The delivered file ships it and nothing measured it, which is a real defect."""
        outcome = run_derived_check(
            _check("AT01", "DOB_YEAR"), _dirt("AT01"), record_layout=_layout("AT01", "DOB_YEAR")
        )
        assert outcome.passed is False
        assert "does not report on" in outcome.detail
        assert "DOB_YEAR" in outcome.detail

    def test_a_field_the_dirt_measured_and_the_layout_omits_does_not_fail(self) -> None:
        """The delivery is right and the document is behind it.

        Failing a correct delivery because its paperwork lags would teach people to stop
        reading the findings.
        """
        outcome = run_derived_check(
            _check("AT01", "ST"), _dirt("AT01", "ST"), record_layout=_layout("AT01")
        )
        assert outcome.passed is True
        assert "does not declare" in outcome.detail
        assert "the layout being behind" in outcome.detail


class TestWithoutALayout:
    """The ordinary delivery, which must answer exactly as it did before 6.22e."""

    def test_the_answer_is_what_it_was(self) -> None:
        outcome = run_derived_check(_check("AT01", "GONE"), _dirt("AT01"))
        assert outcome.passed is False
        assert "missing 1 requested attribute" in outcome.detail
        assert "record layout" not in outcome.detail

    def test_an_empty_layout_is_the_same_as_none(self) -> None:
        outcome = run_derived_check(
            _check("AT01"), _dirt("AT01"), record_layout=RecordLayoutDocument()
        )
        assert outcome.passed is True
        assert "record layout" not in outcome.detail

    def test_a_delivery_with_a_layout_and_no_dirt_is_still_checked(self) -> None:
        """A run whose DIRT could not be read is not a run that checked nothing."""
        outcome = run_derived_check(_check("AT01"), {}, record_layout=_layout("AT01"))
        assert outcome.passed is True


class TestUnresolvedStillWins:
    """ "Could not tell" beats "is not there", in either artifact (6.22a)."""

    def test_a_near_miss_in_the_dirt_is_not_a_missing_attribute(self) -> None:
        outcome = run_derived_check(
            _check("AT01"),
            _dirt("debsc_burs_atyrt_at01_1"),
            record_layout=_layout("debsc_burs_atyrt_at01_1"),
        )
        assert outcome.passed is None
        assert outcome.unresolved == ("AT01",)

    def test_a_near_miss_in_the_layout_alone_is_also_not_missing(self) -> None:
        """One artifact plausibly carrying it is enough to withhold the accusation.

        ``debsc_burs_atyrt_at01_1`` carries ``at01`` as a substring but too many words
        besides for the token rung to settle it, so the ladder declines and 6.22a's
        near-miss rule reports it. The DIRT has nothing resembling it at all — and the
        answer is still "could not tell", not "not delivered".
        """
        outcome = run_derived_check(
            _check("AT01"),
            _dirt("SOMETHING_ELSE"),
            record_layout=_layout("debsc_burs_atyrt_at01_1"),
        )
        assert outcome.passed is None
        assert outcome.unresolved == ("AT01",)

    def test_a_layout_name_the_token_rung_settles_is_resolved_not_a_near_miss(self) -> None:
        """The contrast that makes the test above mean something.

        ``long_at01_name`` is ``AT01`` plus two words, which rung 3 settles. The layout
        then *declares* it and the DIRT does not report on it, which is the unmeasured
        case and a real defect.
        """
        outcome = run_derived_check(
            _check("AT01"), _dirt("SOMETHING_ELSE"), record_layout=_layout("long_at01_name")
        )
        assert outcome.passed is False
        assert "does not report on" in outcome.detail


class TestABorrowedLayout:
    """Every finding resting on one says where it came from (Phase 6.22b)."""

    def test_the_detail_names_the_run_and_the_date(self) -> None:
        outcome = run_derived_check(
            _check("AT01", "DOB_YEAR"),
            _dirt("AT01"),
            record_layout=_layout("AT01", "DOB_YEAR", borrowed_from=41, on="2026-08-14"),
        )
        assert "from run 41 finalized 2026-08-14" in outcome.detail

    def test_a_layout_this_run_uploaded_says_nothing_about_provenance(self) -> None:
        outcome = run_derived_check(_check("AT01"), _dirt("AT01"), record_layout=_layout("AT01"))
        assert "from run" not in outcome.detail
