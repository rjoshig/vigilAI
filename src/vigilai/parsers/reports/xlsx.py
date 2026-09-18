"""Report parsers: one per report type, all sharing one workbook reader.

Implements :class:`vigilai.parsers.base.ReportParser` (ADR-006). Report layouts differ
per type only in which sheets matter, not in how a worksheet is read, so the reading is
shared and each type is a thin subclass that declares its kind. When the real layouts
arrive in-house, a type that needs different handling overrides :meth:`_read_sheet`
without touching the others.

Workbooks are opened read-only and values-only: report files carry hundreds of thousands
of rows and the pipeline never needs formulas or styling.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Sequence

from vigilai.parsers.base import ParseError, ReportCell, ReportDocument, ReportKind, ReportSheet
from vigilai.parsers.masking import DEFAULT_MASKED_COLUMNS, is_masked_column, mask_value

__all__ = [
    "XlsxReportParser",
    "DirtParser",
    "FieldDistributionParser",
    "StateDistributionParser",
    "ScoreDistributionParser",
    "CountsParser",
    "CrossTabParser",
    "BillingParser",
    "parser_for",
    "PARSERS",
]

_LOG: Final = logging.getLogger(__name__)

#: Rows past this are not read. Reports summarise; a sheet longer than this is a data
#: dump and the run should say so rather than consume the memory.
MAX_ROWS: Final[int] = 100_000


class XlsxReportParser:
    """Reads an ``.xlsx`` workbook into :class:`ReportDocument`.

    Attributes:
        kind: The report type this instance produces.
    """

    kind: ReportKind = "dirt"

    def parse(
        self, path: Path, masked_columns: Sequence[str] = DEFAULT_MASKED_COLUMNS
    ) -> ReportDocument:
        """Parse the workbook at ``path``.

        Args:
            path: The ``.xlsx`` file to read.
            masked_columns: Header patterns whose values are masked at parse time, before
                any value is logged or sent to a model (ADR-003).

        Returns:
            The parsed document with every sheet in workbook order.

        Raises:
            ParseError: When the file is missing or openpyxl cannot read it.
        """
        try:
            import openpyxl  # noqa: PLC0415 - lazy so the package imports without it
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ParseError(path, "openpyxl is not installed") from exc

        if not path.exists():
            raise ParseError(path, "file does not exist")
        try:
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - openpyxl raises a variety of types
            raise ParseError(path, f"could not be opened as a workbook ({exc})") from exc

        try:
            sheets = tuple(
                self._read_sheet(workbook[name], masked_columns) for name in workbook.sheetnames
            )
        finally:
            workbook.close()

        _LOG.info(
            "parsed %s report %s: %d sheets, %d rows, %d masked columns",
            self.kind,
            path.name,
            len(sheets),
            sum(len(s.rows) for s in sheets),
            sum(len(s.masked_columns) for s in sheets),
        )
        return ReportDocument(path=path, kind=self.kind, sheets=sheets)

    def _read_sheet(self, worksheet: object, masked_columns: Sequence[str]) -> ReportSheet:
        """Read one worksheet, masking as it goes.

        Args:
            worksheet: The openpyxl read-only worksheet.
            masked_columns: Header patterns to mask.

        Returns:
            The sheet with every cell carrying its A1-style address.
        """
        from openpyxl.utils import get_column_letter  # noqa: PLC0415

        rows_iter = worksheet.iter_rows(max_row=MAX_ROWS)  # type: ignore[attr-defined]
        try:
            first = next(rows_iter)
        except StopIteration:
            empty_name = str(worksheet.title)  # type: ignore[attr-defined]
            return ReportSheet(name=empty_name, header=(), rows=())

        header = tuple("" if c.value is None else str(c.value).strip() for c in first)
        masked_flags = tuple(is_masked_column(h, masked_columns) if h else False for h in header)
        masked = frozenset(h for h, flag in zip(header, masked_flags) if flag and h)

        rows: list[tuple[ReportCell, ...]] = []
        for row_index, row in enumerate(rows_iter, start=2):
            cells: list[ReportCell] = []
            for column_index, cell in enumerate(row):
                value = cell.value
                if column_index < len(masked_flags) and masked_flags[column_index]:
                    value = mask_value(value)
                address = f"{get_column_letter(column_index + 1)}{row_index}"
                cells.append(ReportCell(address=address, value=value))
            if any(c.value is not None for c in cells):
                rows.append(tuple(cells))

        return ReportSheet(
            name=str(worksheet.title),  # type: ignore[attr-defined]
            header=header,
            rows=tuple(rows),
            masked_columns=masked,
        )


class DirtParser(XlsxReportParser):
    """The data integrity report: summary, per-attribute statistics, masked sample rows."""

    kind: ReportKind = "dirt"


class FieldDistributionParser(XlsxReportParser):
    """Per-field value distributions and null rates."""

    kind: ReportKind = "field_distribution"


class StateDistributionParser(XlsxReportParser):
    """Record counts per state code."""

    kind: ReportKind = "state_distribution"


class ScoreDistributionParser(XlsxReportParser):
    """Record counts per score band."""

    kind: ReportKind = "score_distribution"


class CountsParser(XlsxReportParser):
    """The number-flow report: counts at each waterfall step."""

    kind: ReportKind = "counts"


class CrossTabParser(XlsxReportParser):
    """Two-dimensional breakdowns, e.g. state by score band."""

    kind: ReportKind = "cross_tab"


class BillingParser(XlsxReportParser):
    """Billed record counts."""

    kind: ReportKind = "billing"


#: Every report type the pipeline can read, by kind.
PARSERS: Final[dict[ReportKind, type[XlsxReportParser]]] = {
    "dirt": DirtParser,
    "field_distribution": FieldDistributionParser,
    "state_distribution": StateDistributionParser,
    "score_distribution": ScoreDistributionParser,
    "counts": CountsParser,
    "cross_tab": CrossTabParser,
    "billing": BillingParser,
}


def parser_for(kind: ReportKind) -> XlsxReportParser:
    """Return the parser for a report kind.

    Args:
        kind: The report type.

    Returns:
        A ready-to-use parser instance.

    Raises:
        KeyError: When the kind has no parser, which is a programming error rather than a
            data problem: the caller validated the kind at upload time.
    """
    return PARSERS[kind]()
