"""Tests for the report workbook parsers, including the masking tripwire."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from vigilai.parsers import ParseError, parser_for
from vigilai.parsers.reports.xlsx import PARSERS

#: Anything shaped like a real identifier must never survive parsing (ADR-003).
_PII_TRIPWIRE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _report(fixtures_root: Path, case: dict[str, Any], kind: str):
    return parser_for(kind).parse(fixtures_root / case["reports"][kind])  # type: ignore[arg-type]


def test_every_kind_has_a_parser() -> None:
    assert set(PARSERS) == {
        "dirt",
        "field_distribution",
        "state_distribution",
        "score_distribution",
        "counts",
        "cross_tab",
        "billing",
    }


def test_parser_reports_its_kind() -> None:
    assert parser_for("counts").kind == "counts"


def test_dirt_sheets_are_read_in_order(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "dirt")
    assert [s.name for s in document.sheets] == ["Summary", "Attributes", "Sample"]


def test_cells_carry_their_addresses(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "dirt")
    attributes = document.sheet("Attributes")
    assert attributes is not None
    first = attributes.rows[0]
    assert first[0].address == "A2"
    assert first[0].value == "SCORE_V3"


def test_label_lookup_survives_row_position(fixtures_root: Path, cases: dict[str, Any]) -> None:
    case = cases["baseline_match"]
    document = _report(fixtures_root, case, "dirt")
    summary = document.sheet("Summary")
    assert summary is not None
    cell = summary.lookup("Total rows")
    assert cell is not None
    assert cell.value == case["expected"]["accepts"]


def test_label_lookup_is_case_insensitive(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "dirt")
    summary = document.sheet("Summary")
    assert summary is not None
    assert summary.lookup("total ROWS") is not None


def test_label_lookup_returns_none_when_absent(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "dirt")
    summary = document.sheet("Summary")
    assert summary is not None
    assert summary.lookup("Not a label") is None


def test_column_access_by_header(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["geography_extra_state"], "state_distribution")
    states = document.sheet("States")
    assert states is not None
    assert [c.value for c in states.column("State")] == ["IL", "AZ", "TX", "NV"]


def test_unknown_column_returns_empty(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "state_distribution")
    states = document.sheet("States")
    assert states is not None
    assert states.column("Nope") == ()


def test_pii_columns_are_masked_at_parse_time(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "dirt")
    sample = document.sheet("Sample")
    assert sample is not None
    assert sample.masked_columns == frozenset({"SSN_LAST4", "FIRST_NAME"})
    for cell in sample.column("FIRST_NAME"):
        assert set(str(cell.value)[:-1]) <= {"*"}


def test_analytic_columns_are_not_masked(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "dirt")
    sample = document.sheet("Sample")
    assert sample is not None
    assert [c.value for c in sample.column("ST")] == ["IL", "AZ"]


def test_no_parsed_value_looks_like_an_identifier(
    fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """Tripwire: a future fixture that leaks a real-looking identifier fails here."""
    for case in cases.values():
        for kind in case["reports"]:
            document = _report(fixtures_root, case, kind)
            for sheet in document.sheets:
                for row in sheet.rows:
                    for cell in row:
                        assert not _PII_TRIPWIRE.search(str(cell.value))


def test_counts_flow_is_readable(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "counts")
    flow = document.sheet("Flow")
    assert flow is not None
    assert flow.header == ("Step", "Records in", "Removed", "Records out")
    accepts = flow.lookup("Accepts", value_column=3)
    assert accepts is not None
    assert accepts.value == cases["baseline_match"]["expected"]["accepts"]


def test_reconciling_case_adds_up(fixtures_root: Path, cases: dict[str, Any]) -> None:
    case = cases["baseline_match"]
    document = _report(fixtures_root, case, "counts")
    flow = document.sheet("Flow")
    assert flow is not None
    accepts = flow.lookup("Accepts", value_column=3)
    rejects = flow.lookup("Rejects", value_column=3)
    assert accepts is not None and rejects is not None
    assert accepts.value + rejects.value == case["expected"]["input_count"]


def test_broken_case_does_not_add_up(fixtures_root: Path, cases: dict[str, Any]) -> None:
    case = cases["counts_do_not_reconcile"]
    assert case["expected"]["reconciles"] is False
    document = _report(fixtures_root, case, "counts")
    flow = document.sheet("Flow")
    assert flow is not None
    accepts = flow.lookup("Accepts", value_column=3)
    rejects = flow.lookup("Rejects", value_column=3)
    assert accepts is not None and rejects is not None
    assert accepts.value + rejects.value == case["expected"]["input_count"] - 588


def test_sheet_lookup_is_case_insensitive(fixtures_root: Path, cases: dict[str, Any]) -> None:
    document = _report(fixtures_root, cases["baseline_match"], "dirt")
    assert document.sheet("summary") is not None
    assert document.sheet("nope") is None


def test_missing_file_raises_parse_error(tmp_path: Path) -> None:
    with pytest.raises(ParseError, match="does not exist"):
        parser_for("dirt").parse(tmp_path / "absent.xlsx")


def test_non_workbook_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "not_a_book.xlsx"
    path.write_text("plain text", encoding="utf-8")
    with pytest.raises(ParseError, match="workbook"):
        parser_for("dirt").parse(path)
