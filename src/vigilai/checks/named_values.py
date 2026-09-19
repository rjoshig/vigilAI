"""Resolving named values out of parsed reports.

A named value is a pointer into a report: report type, sheet, and either a cell address
or a label lookup (``docs/design.md`` "Configurable checks"). Label lookup is preferred
because it survives inserted rows. Admins define these in the admin-ui; the worker
resolves them at run time and hands the numbers to the expression evaluator.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Final, Literal, Mapping, Sequence

from vigilai.parsers.base import ReportDocument, ReportKind

__all__ = ["NamedValue", "resolve", "resolve_all", "to_number"]

_LOG: Final = logging.getLogger(__name__)

LocatorKind = Literal["cell", "label"]

_CELL_RE: Final = re.compile(r"^([A-Za-z]+)(\d+)$")


@dataclass(frozen=True, slots=True)
class NamedValue:
    """A pointer into a report that checks refer to by name.

    Attributes:
        name: The identifier used in expressions, e.g. ``"billing_count"``.
        report_kind: Which report to read.
        sheet: Which sheet.
        kind: ``"cell"`` for a fixed address, ``"label"`` for a label lookup.
        cell: The A1-style address, for ``"cell"``.
        label: The label text to find, for ``"label"``.
        label_column: Zero-based column holding the label.
        value_column: Zero-based column holding the value.
        description: A plain sentence, shown in the admin-ui and on findings.
    """

    name: str
    report_kind: ReportKind
    sheet: str
    kind: LocatorKind = "label"
    cell: str = ""
    label: str = ""
    label_column: int = 0
    value_column: int = 1
    description: str = ""


def resolve(named: NamedValue, reports: Mapping[ReportKind, ReportDocument]) -> object | None:
    """Resolve one named value against the parsed reports.

    Args:
        named: The pointer.
        reports: The parsed reports, by kind.

    Returns:
        The value, or ``None`` when the report, the sheet, or the target is absent. The
        caller turns ``None`` into a "could not evaluate" finding rather than skipping
        the check.
    """
    document = reports.get(named.report_kind)
    if document is None:
        _LOG.info("named value %s: report %s was not supplied", named.name, named.report_kind)
        return None

    sheet = document.sheet(named.sheet)
    if sheet is None:
        _LOG.info("named value %s: sheet %r not found", named.name, named.sheet)
        return None

    if named.kind == "cell":
        match = _CELL_RE.match(named.cell.strip())
        if match is None:
            _LOG.info("named value %s: %r is not an A1 address", named.name, named.cell)
            return None
        wanted = named.cell.strip().upper()
        for row in sheet.rows:
            for cell in row:
                if cell.address == wanted:
                    return cell.value
        return None

    found = sheet.lookup(
        named.label, value_column=named.value_column, label_column=named.label_column
    )
    return None if found is None else found.value


def resolve_all(
    named_values: Sequence[NamedValue], reports: Mapping[ReportKind, ReportDocument]
) -> dict[str, object]:
    """Resolve every named value.

    Args:
        named_values: The pointers.
        reports: The parsed reports, by kind.

    Returns:
        Name to value. An unresolvable pointer maps to ``None`` rather than being
        omitted, so the evaluator can name exactly what was missing.
    """
    return {named.name: resolve(named, reports) for named in named_values}


def to_number(value: object) -> float | None:
    """Read a number out of a report cell.

    Report cells arrive as numbers when the workbook stored them as numbers, and as
    strings such as ``"1,204"`` when it did not.

    Args:
        value: The cell value.

    Returns:
        The number, or ``None`` when the cell holds something that is not one.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip().rstrip("%")
        try:
            number = float(cleaned)
        except ValueError:
            return None
        return number / 100.0 if value.strip().endswith("%") else number
    return None
