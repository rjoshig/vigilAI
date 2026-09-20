"""OSL parser for PDF requirement specs.

Some OSLs arrive as PDF rather than Word. The text is read page by page with
``pypdf`` and cut into sections on numbered heading lines (``3 Geography``,
``4.2 Exclusions``), the same shape the ``.docx`` parser produces, so every later
stage is indifferent to which format arrived (ADR-006). Tables in a PDF have no
structure to recover; their lines are kept as paragraphs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

from greenlight_ai.parsers.base import OslDocument, OslSection, ParseError

__all__ = ["PdfOslParser"]

_LOG: Final = logging.getLogger(__name__)

#: A heading line: a section number, then the heading text. Kept strict (a number,
#: whitespace, a capital letter) so a sentence that starts with a figure is not a
#: heading.
_HEADING: Final = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+([A-Z][^\n]{0,120})\s*$")

_PREAMBLE_NUMBER: Final = "0"
_PREAMBLE_HEADING: Final = "Preamble"


class PdfOslParser:
    """Parses a ``.pdf`` requirement spec into sections."""

    def parse(self, path: Path) -> OslDocument:
        """Parse the OSL at ``path``.

        Args:
            path: The ``.pdf`` file to read.

        Returns:
            The parsed document, sections in reading order.

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
                lines.extend((page.extract_text() or "").splitlines())
        except Exception as exc:  # noqa: BLE001 - pypdf raises a mix of exceptions
            raise ParseError(path, f"could not be opened as a PDF ({exc})") from exc

        text_lines = [line.strip() for line in lines if line.strip()]
        if not text_lines:
            raise ParseError(path, "no text could be read; a scanned PDF needs OCR first")

        title = ""
        sections: list[OslSection] = []
        number, heading, level = _PREAMBLE_NUMBER, _PREAMBLE_HEADING, 1
        paragraphs: list[str] = []
        for line in text_lines:
            match = _HEADING.match(line)
            if match:
                if paragraphs or sections:
                    sections.append(
                        OslSection(
                            number=number,
                            heading=heading,
                            level=level,
                            paragraphs=tuple(paragraphs),
                        )
                    )
                elif not title:
                    title = ""
                number, heading = match.group(1), match.group(2).strip()
                level = number.count(".") + 1
                paragraphs = []
            elif not sections and number == _PREAMBLE_NUMBER and not title and not paragraphs:
                title = line
            else:
                paragraphs.append(line)
        sections.append(
            OslSection(number=number, heading=heading, level=level, paragraphs=tuple(paragraphs))
        )
        sections = [s for s in sections if s.paragraphs or s.number != _PREAMBLE_NUMBER]

        _LOG.info("parsed OSL %s: %d sections (pdf)", path.name, len(sections))
        return OslDocument(path=path, title=title or path.stem, sections=tuple(sections))
