"""OSL parser for PDF requirement specs.

Some OSLs arrive as PDF rather than Word. The text is read page by page with
``pypdf`` and cut into sections on numbered heading lines (``3 Geography``,
``4.2 Exclusions``), the same shape the ``.docx`` parser produces, so every later
stage is indifferent to which format arrived (ADR-006).

**Tables (Phase 6.21e).** Until this phase a PDF's tables were flattened into
paragraphs, and that was the worst kind of defect: most ``criteria`` requirements live
in a table, so the same specification delivered as a PDF yielded fewer requirements
than delivered as Word — and *fewer requirements* reads downstream as *nothing wrong*.
A PDF has no table structure to recover, so this reads the one thing the text stream
does preserve: a row is a line whose cells are separated by a run of whitespace, and a
table is a run of consecutive lines that all split the same way. Where the extractor
offers a layout-preserving mode it is used, because that is what keeps those runs of
whitespace intact.

The heuristic is deliberately conservative — a consistent column count, at least two
columns, at least two lines — so prose is never mistaken for a table. It will meet real
PDFs for the first time in [`phase-7.md`](../../../docs/phase-7.md), and the rule to
adjust is :func:`_tabular`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final, Sequence

from greenlight_ai.parsers.base import OslDocument, OslSection, OslTable, ParseError

__all__ = ["MIN_TABLE_COLUMNS", "MIN_TABLE_ROWS", "PdfOslParser"]

_LOG: Final = logging.getLogger(__name__)

#: A heading line: a section number, then the heading text. Kept strict (a number,
#: whitespace, a capital letter) so a sentence that starts with a figure is not a
#: heading.
_HEADING: Final = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+([A-Z][^\n]{0,120})\s*$")

#: What separates two cells on one line: a tab, or a run of spaces. One space is a word
#: break inside a cell, which is why the run must be at least two.
_CELL_GAP: Final = re.compile(r"\t+|\s{2,}")

#: Below this a "row" is a sentence with an odd gap in it, not a table row.
MIN_TABLE_COLUMNS: Final[int] = 2

#: Header plus one row. A single line that happens to split is not a table.
MIN_TABLE_ROWS: Final[int] = 2

_PREAMBLE_NUMBER: Final = "0"
_PREAMBLE_HEADING: Final = "Preamble"


def _cells(line: str) -> tuple[str, ...]:
    """Split one line into cells on runs of whitespace.

    Args:
        line: One line of extracted text.

    Returns:
        The non-empty cells, stripped. A line with no wide gap gives one cell, which is
        how prose is told apart from a row.
    """
    return tuple(cell.strip() for cell in _CELL_GAP.split(line.strip()) if cell.strip())


def _tabular(lines: Sequence[str], start: int) -> int:
    """How many consecutive lines from ``start`` form one table.

    Args:
        lines: The section's lines.
        start: Where to begin.

    Returns:
        The number of lines, or ``0`` when this is not the start of a table. A table is
        a run of lines that all split into the *same* number of cells, at least
        :data:`MIN_TABLE_COLUMNS` of them, and there must be at least
        :data:`MIN_TABLE_ROWS` such lines. Requiring the width to be identical is what
        keeps a paragraph with one wide gap in it from becoming a one-column table.
    """
    width = len(_cells(lines[start]))
    if width < MIN_TABLE_COLUMNS:
        return 0
    count = 0
    for line in lines[start:]:
        if len(_cells(line)) != width:
            break
        count += 1
    return count if count >= MIN_TABLE_ROWS else 0


def _split(lines: Sequence[str]) -> tuple[tuple[str, ...], tuple[OslTable, ...]]:
    """Separate a section's lines into prose and tables.

    Args:
        lines: The section's lines, in reading order.

    Returns:
        The paragraphs and the tables, each in the order they appeared.
    """
    paragraphs: list[str] = []
    tables: list[OslTable] = []
    index = 0
    while index < len(lines):
        span = _tabular(lines, index)
        if span:
            rows = [_cells(line) for line in lines[index : index + span]]
            tables.append(OslTable(index=len(tables) + 1, header=rows[0], rows=tuple(rows[1:])))
            index += span
        else:
            paragraphs.append(lines[index])
            index += 1
    return tuple(paragraphs), tuple(tables)


class PdfOslParser:
    """Parses a ``.pdf`` requirement spec into sections."""

    def parse(self, path: Path) -> OslDocument:
        """Parse the OSL at ``path``.

        Args:
            path: The ``.pdf`` file to read.

        Returns:
            The parsed document, sections in reading order, each with its prose and any
            tables the text stream still carries the shape of.

        Raises:
            ParseError: When the file is missing, cannot be opened, or holds no text
                (a scanned PDF has none; it would need OCR, which this does not do).
        """
        try:
            from pypdf import PdfReader  # noqa: PLC0415 - lazy so the package imports without it
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ParseError(path, "pypdf is not installed") from exc

        if not path.exists():
            raise ParseError(path, "file does not exist")
        try:
            reader = PdfReader(str(path))
            lines: list[str] = []
            for page in reader.pages:
                lines.extend(_extract(page).splitlines())
        except Exception as exc:  # noqa: BLE001 - pypdf raises a mix of exceptions
            raise ParseError(path, f"could not be opened as a PDF ({exc})") from exc

        # Trailing space is stripped, leading is not: a table's first column may be
        # indented, and the gap that survives is the only thing saying where a cell
        # ends. A line that is only whitespace is dropped.
        text_lines = [line.rstrip() for line in lines if line.strip()]
        if not text_lines:
            raise ParseError(path, "no text could be read; a scanned PDF needs OCR first")

        title = ""
        sections: list[OslSection] = []
        number, heading, level = _PREAMBLE_NUMBER, _PREAMBLE_HEADING, 1
        body: list[str] = []
        for line in text_lines:
            match = _HEADING.match(line)
            if match:
                if body or sections:
                    paragraphs, tables = _split(body)
                    sections.append(
                        OslSection(
                            number=number,
                            heading=heading,
                            level=level,
                            paragraphs=paragraphs,
                            tables=tables,
                        )
                    )
                number, heading = match.group(1), match.group(2).strip()
                level = number.count(".") + 1
                body = []
            elif not sections and number == _PREAMBLE_NUMBER and not title and not body:
                title = line.strip()
            else:
                body.append(line)

        paragraphs, tables = _split(body)
        sections.append(
            OslSection(
                number=number,
                heading=heading,
                level=level,
                paragraphs=paragraphs,
                tables=tables,
            )
        )
        sections = [s for s in sections if s.paragraphs or s.tables or s.number != _PREAMBLE_NUMBER]

        _LOG.info(
            "parsed OSL %s: %d sections, %d tables (pdf)",
            path.name,
            len(sections),
            sum(len(s.tables) for s in sections),
        )
        return OslDocument(path=path, title=title or path.stem, sections=tuple(sections))


def _extract(page: object) -> str:
    """Read one page's text, preserving layout where the extractor can.

    Layout mode keeps the horizontal whitespace that is the only remaining evidence of
    where one cell ends and the next begins. Not every pypdf version offers it, and a
    page it cannot lay out raises rather than returning nothing, so both cases fall
    back to the plain extraction that was here before.

    Args:
        page: A ``pypdf`` page.

    Returns:
        The page's text, or an empty string when it has none.
    """
    extract = getattr(page, "extract_text", None)
    if extract is None:  # pragma: no cover - not a pypdf page
        return ""
    try:
        return str(extract(extraction_mode="layout") or "")
    except Exception:  # noqa: BLE001 - any refusal means fall back, never fail the parse
        return str(extract() or "")
