"""Tests for the PDF OSL parser and the parser dispatcher (ADR-006)."""

from __future__ import annotations

from pathlib import Path

import pytest

from greenlight_ai.parsers import DocxOslParser, PdfOslParser, ParseError, osl_parser_for


def write_pdf(path: Path, lines: list[str]) -> None:
    """Write a one-page PDF with Helvetica text lines, no library needed."""
    content = (
        "BT /F1 12 Tf 72 720 Td 16 TL "
        + " ".join(f"({line.replace('(', '[').replace(')', ']')}) Tj T*" for line in lines)
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n"
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


def test_a_pdf_osl_is_cut_into_numbered_sections(tmp_path: Path) -> None:
    path = tmp_path / "osl.pdf"
    write_pdf(
        path,
        [
            "Order Specification Letter",
            "1 Purpose",
            "A prescreen campaign.",
            "3 Geography",
            "Include only consumers whose current address is in Illinois or Arizona.",
            "4.2 Exclusions",
            "Exclude any consumer recorded as deceased.",
        ],
    )
    document = PdfOslParser().parse(path)
    assert document.title == "Order Specification Letter"
    assert [(s.number, s.heading, s.level) for s in document.sections] == [
        ("1", "Purpose", 1),
        ("3", "Geography", 1),
        ("4.2", "Exclusions", 2),
    ]
    assert document.sections[1].paragraphs == (
        "Include only consumers whose current address is in Illinois or Arizona.",
    )


def test_a_pdf_with_no_text_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    write_pdf(path, [])
    with pytest.raises(ParseError, match="OCR"):
        PdfOslParser().parse(path)


def test_the_dispatcher_picks_by_suffix(tmp_path: Path) -> None:
    assert isinstance(osl_parser_for(tmp_path / "a.docx"), DocxOslParser)
    assert isinstance(osl_parser_for(tmp_path / "a.PDF"), PdfOslParser)
    with pytest.raises(ParseError, match=r"\.docx or \.pdf"):
        osl_parser_for(tmp_path / "a.xlsx")


# --- tables (Phase 6.21e) --------------------------------------------------------------


def test_a_criteria_table_survives_as_a_table(tmp_path: Path) -> None:
    """The defect this closes.

    Most ``criteria`` requirements live in a table. Before 6.21e a PDF's table was
    flattened into paragraphs, so the same specification delivered as a PDF yielded
    fewer requirements than delivered as Word — and downstream, fewer requirements
    reads as nothing wrong.
    """
    path = tmp_path / "osl.pdf"
    write_pdf(
        path,
        [
            "Order Specification Letter",
            "4 Criteria",
            "Apply the following to every record.",
            "Field      Operator    Value",
            "score      >=          755",
            "age        >=          21",
            "Anything below the threshold is rejected.",
        ],
    )

    section = next(s for s in PdfOslParser().parse(path).sections if s.number == "4")

    assert len(section.tables) == 1
    table = section.tables[0]
    assert table.header == ("Field", "Operator", "Value")
    assert table.rows == (("score", ">=", "755"), ("age", ">=", "21"))
    # The prose around it is still prose.
    assert section.paragraphs == (
        "Apply the following to every record.",
        "Anything below the threshold is rejected.",
    )
    # And it renders for stage 2 exactly as a Word table does.
    assert "score | >= | 755" in table.as_text()


def test_prose_is_never_mistaken_for_a_table(tmp_path: Path) -> None:
    """A conservative heuristic is the point: a false table is worse than none."""
    path = tmp_path / "osl.pdf"
    write_pdf(
        path,
        [
            "Order Specification Letter",
            "3 Geography",
            "Include only consumers whose address is in Illinois or Arizona.",
            "Exclude everybody else.",
        ],
    )

    section = next(s for s in PdfOslParser().parse(path).sections if s.number == "3")
    assert section.tables == ()
    assert len(section.paragraphs) == 2


def test_one_line_that_happens_to_split_is_not_a_table(tmp_path: Path) -> None:
    """Header plus one row is the floor; a lone line is a line."""
    path = tmp_path / "osl.pdf"
    write_pdf(
        path,
        [
            "Order Specification Letter",
            "5 Notes",
            "Contact        the delivery team",
            "Nothing else applies.",
        ],
    )

    section = next(s for s in PdfOslParser().parse(path).sections if s.number == "5")
    assert section.tables == ()


def test_a_ragged_run_ends_the_table_rather_than_corrupting_it(tmp_path: Path) -> None:
    """A row of a different width is the next thing, not a row with a missing cell."""
    path = tmp_path / "osl.pdf"
    write_pdf(
        path,
        [
            "Order Specification Letter",
            "4 Criteria",
            "Field      Operator    Value",
            "score      >=          755",
            "See        appendix",
        ],
    )

    section = next(s for s in PdfOslParser().parse(path).sections if s.number == "4")
    assert len(section.tables) == 1
    assert section.tables[0].rows == (("score", ">=", "755"),)
