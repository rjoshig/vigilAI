"""Parsers for the OSL, the ETL config, and each report type.

Everything here sits behind a Protocol (ADR-006) because the real file layouts arrive
last and only in-house. The pipeline imports the Protocols and the factory, never a
concrete class.
"""

from greenlight_ai.parsers.base import (
    ConfigBlock,
    ConfigDocument,
    ConfigParser,
    OslDocument,
    OslParser,
    OslSection,
    OslTable,
    ParseError,
    ReportCell,
    ReportDocument,
    ReportKind,
    ReportParser,
    ReportSheet,
)
from greenlight_ai.parsers.config_json import JsonConfigParser, is_technical
from greenlight_ai.parsers.masking import DEFAULT_MASKED_COLUMNS, is_masked_column, mask_value
from greenlight_ai.parsers.osl import OSL_SUFFIXES, osl_parser_for
from greenlight_ai.parsers.osl_docx import DocxOslParser
from greenlight_ai.parsers.osl_pdf import PdfOslParser
from greenlight_ai.parsers.reports.xlsx import PARSERS, XlsxReportParser, parser_for

__all__ = [
    "ConfigBlock",
    "ConfigDocument",
    "ConfigParser",
    "DEFAULT_MASKED_COLUMNS",
    "DocxOslParser",
    "JsonConfigParser",
    "OSL_SUFFIXES",
    "PdfOslParser",
    "osl_parser_for",
    "OslDocument",
    "OslParser",
    "OslSection",
    "OslTable",
    "PARSERS",
    "ParseError",
    "ReportCell",
    "ReportDocument",
    "ReportKind",
    "ReportParser",
    "ReportSheet",
    "XlsxReportParser",
    "is_masked_column",
    "is_technical",
    "mask_value",
    "parser_for",
]
