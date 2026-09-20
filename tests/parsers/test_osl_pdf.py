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
