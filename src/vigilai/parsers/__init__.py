"""Parsers for the OSL, the ETL config, and each report type.

Everything here sits behind a Protocol (ADR-006) because the real file layouts arrive
last and only in-house. The pipeline imports the Protocols and the factory, never a
concrete class.
"""

from vigilai.parsers.base import (
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
from vigilai.parsers.config_json import JsonConfigParser, is_technical
from vigilai.parsers.masking import DEFAULT_MASKED_COLUMNS, is_masked_column, mask_value
from vigilai.parsers.osl_docx import DocxOslParser
from vigilai.parsers.reports.xlsx import PARSERS, XlsxReportParser, parser_for

__all__ = [
    "ConfigBlock",
    "ConfigDocument",
    "ConfigParser",
    "DEFAULT_MASKED_COLUMNS",
    "DocxOslParser",
    "JsonConfigParser",
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
