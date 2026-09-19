"""Tests for the parsed-document value objects and ParseError."""

from __future__ import annotations

import copy
import pickle
from pathlib import Path

from greenlight_ai.parsers import ParseError
from greenlight_ai.parsers.base import OslSection, OslTable, ReportCell, ReportSheet


def test_parse_error_message_names_the_file_and_reason() -> None:
    error = ParseError(Path("/tmp/order.json"), "is not valid JSON")
    assert str(error) == "order.json: is not valid JSON"


def test_parse_error_survives_pickling() -> None:
    """The worker carries a failure across a process boundary when a job fails."""
    error = ParseError(Path("/tmp/order.json"), "is not valid JSON")
    restored = pickle.loads(pickle.dumps(error))
    assert isinstance(restored, ParseError)
    assert restored.path == error.path
    assert restored.reason == error.reason
    assert str(restored) == str(error)


def test_parse_error_survives_copying() -> None:
    error = ParseError(Path("/tmp/order.json"), "is not valid JSON")
    assert str(copy.copy(error)) == str(error)
    assert str(copy.deepcopy(error)) == str(error)


def test_section_without_a_number_does_not_invent_one() -> None:
    section = OslSection(number="", heading="Notes", level=1, paragraphs=("text",))
    assert section.ref == "OSL section Notes"


def test_section_ref_includes_the_number_when_present() -> None:
    section = OslSection(number="3.1", heading="Geography", level=2, paragraphs=())
    assert section.ref == "OSL section 3.1 Geography"


def test_table_pads_nothing_when_rows_match_the_header() -> None:
    table = OslTable(index=1, header=("A", "B"), rows=(("1", "2"),))
    assert table.as_text() == "A | B\n1 | 2"


def test_sheet_column_is_empty_for_an_unknown_header() -> None:
    sheet = ReportSheet(name="S", header=("A",), rows=((ReportCell("A2", 1),),))
    assert sheet.column("missing") == ()


def test_sheet_lookup_skips_short_rows() -> None:
    sheet = ReportSheet(
        name="S",
        header=("Label", "Value"),
        rows=((ReportCell("A2", "only"),), (ReportCell("A3", "Total"), ReportCell("B3", 7))),
    )
    cell = sheet.lookup("Total")
    assert cell is not None and cell.value == 7
