"""One parser per report type (ADR-006)."""

from vigilai.parsers.reports.xlsx import (
    PARSERS,
    BillingParser,
    CountsParser,
    CrossTabParser,
    DirtParser,
    FieldDistributionParser,
    ScoreDistributionParser,
    StateDistributionParser,
    XlsxReportParser,
    parser_for,
)

__all__ = [
    "PARSERS",
    "BillingParser",
    "CountsParser",
    "CrossTabParser",
    "DirtParser",
    "FieldDistributionParser",
    "ScoreDistributionParser",
    "StateDistributionParser",
    "XlsxReportParser",
    "parser_for",
]
