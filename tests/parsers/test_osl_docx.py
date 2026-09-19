"""Tests for the OSL Word parser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from greenlight_ai.parsers import DocxOslParser, ParseError


@pytest.fixture()
def parser() -> DocxOslParser:
    return DocxOslParser()


@pytest.fixture()
def baseline(parser: DocxOslParser, fixtures_root: Path, cases: dict[str, Any]):
    return parser.parse(fixtures_root / cases["baseline_match"]["osl"])


def test_title_is_read(baseline) -> None:
    assert baseline.title.startswith("Order Specification Letter")


def test_sections_are_numbered_and_in_order(baseline) -> None:
    numbers = [s.number for s in baseline.sections]
    assert numbers == ["1", "2", "3", "4", "5", "6", "7"]


def test_heading_number_is_split_from_text(baseline) -> None:
    geography = baseline.section("3")
    assert geography is not None
    assert geography.heading == "Geography"
    assert geography.level == 1


def test_paragraph_text_is_verbatim(baseline) -> None:
    """The OSL is the source of truth (ADR-002): wording must not be normalised."""
    geography = baseline.section("3")
    assert geography is not None
    assert "Illinois or Arizona" in geography.paragraphs[0]


def test_criteria_table_is_parsed_with_its_header(baseline) -> None:
    criteria = baseline.section("4")
    assert criteria is not None
    assert len(criteria.tables) == 1
    table = criteria.tables[0]
    assert table.header == ("Attribute", "Condition", "Threshold")
    assert ("score", "at least", "755") in table.rows


def test_table_renders_as_prompt_text(baseline) -> None:
    criteria = baseline.section("4")
    assert criteria is not None
    text = criteria.tables[0].as_text()
    assert text.splitlines()[0] == "Attribute | Condition | Threshold"
    assert "score | at least | 755" in text


def test_section_ref_is_human_readable(baseline) -> None:
    geography = baseline.section("3")
    assert geography is not None
    assert geography.ref == "OSL section 3 Geography"


def test_section_as_text_includes_paragraphs_and_tables(baseline) -> None:
    criteria = baseline.section("4")
    assert criteria is not None
    text = criteria.as_text()
    assert text.startswith("4 Credit criteria")
    assert "Attribute | Condition | Threshold" in text


def test_attribute_list_is_captured_as_paragraphs(baseline) -> None:
    attributes = baseline.section("5")
    assert attributes is not None
    joined = " ".join(attributes.paragraphs)
    assert "1. SCORE_V3" in joined
    assert "10. BK_24M" in joined


def test_unknown_section_returns_none(baseline) -> None:
    assert baseline.section("99") is None


def test_mismatch_case_states_the_config_threshold_in_the_osl(
    parser: DocxOslParser, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """The OSL always says 755; only the config drifts. Guards the fixture's premise."""
    document = parser.parse(fixtures_root / cases["score_value_mismatch"]["osl"])
    criteria = document.section("4")
    assert criteria is not None
    assert ("score", "at least", "755") in criteria.tables[0].rows


def test_missing_file_raises_parse_error(parser: DocxOslParser, tmp_path: Path) -> None:
    with pytest.raises(ParseError, match="does not exist"):
        parser.parse(tmp_path / "absent.docx")


def test_non_docx_raises_parse_error(parser: DocxOslParser, tmp_path: Path) -> None:
    path = tmp_path / "not_a_doc.docx"
    path.write_text("plain text", encoding="utf-8")
    with pytest.raises(ParseError, match="Word document"):
        parser.parse(path)
