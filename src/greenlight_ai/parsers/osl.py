"""Pick the OSL parser by file type (ADR-006)."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from greenlight_ai.parsers.base import OslParser, ParseError
from greenlight_ai.parsers.osl_docx import DocxOslParser
from greenlight_ai.parsers.osl_pdf import PdfOslParser

__all__ = ["OSL_SUFFIXES", "osl_parser_for"]

#: The formats an OSL may arrive in, as the upload forms offer them.
OSL_SUFFIXES: Final[tuple[str, ...]] = (".docx", ".pdf")


def osl_parser_for(path: Path) -> OslParser:
    """The parser for an OSL file, by its suffix.

    Args:
        path: The OSL.

    Returns:
        A Word or a PDF parser.

    Raises:
        ParseError: When the suffix is neither.
    """
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return DocxOslParser()
    if suffix == ".pdf":
        return PdfOslParser()
    raise ParseError(
        path, f"an OSL must be .docx or .pdf, not {suffix or 'a file without a suffix'}"
    )
