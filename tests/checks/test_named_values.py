"""Tests for resolving named values out of parsed reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from greenlight_ai.checks.named_values import NamedValue, resolve, resolve_all, to_number
from greenlight_ai.parsers import parser_for
from greenlight_ai.parsers.base import ReportDocument, ReportKind


@pytest.fixture()
def reports(fixtures_root: Path, cases: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    case = cases["baseline_match"]
    return {
        kind: parser_for(kind).parse(fixtures_root / path)  # type: ignore[arg-type]
        for kind, path in case["reports"].items()
    }


def _billing(**kwargs: Any) -> NamedValue:
    values: dict[str, Any] = {
        "name": "billing_count",
        "report_kind": "billing",
        "sheet": "Summary",
        "label": "Billing count",
    }
    values.update(kwargs)
    return NamedValue(**values)


# --- label lookup ----------------------------------------------------------------------


def test_a_label_lookup_finds_the_value(
    reports: dict[ReportKind, ReportDocument], cases: dict[str, Any]
) -> None:
    assert resolve(_billing(), reports) == cases["baseline_match"]["expected"]["accepts"]


def test_a_label_lookup_is_case_insensitive(reports: dict[ReportKind, ReportDocument]) -> None:
    assert resolve(_billing(label="BILLING COUNT"), reports) is not None


def test_a_label_lookup_survives_an_inserted_row(reports: dict[ReportKind, ReportDocument]) -> None:
    """The reason label lookup is preferred over a fixed cell address."""
    document = reports["dirt"]
    summary = document.sheet("Summary")
    assert summary is not None
    rows = list(summary.rows)
    total_row_index = next(
        i for i, row in enumerate(rows) if str(row[0].value).strip() == "Total rows"
    )
    assert total_row_index > 0  # it is not the first row, so a shift is possible
    named = NamedValue(name="total", report_kind="dirt", sheet="Summary", label="Total rows")
    assert resolve(named, reports) is not None


def test_an_absent_label_resolves_to_none(reports: dict[ReportKind, ReportDocument]) -> None:
    assert resolve(_billing(label="Not a label"), reports) is None


def test_a_custom_value_column_is_respected(reports: dict[ReportKind, ReportDocument]) -> None:
    named = NamedValue(
        name="accepts",
        report_kind="counts",
        sheet="Flow",
        label="Accepts",
        value_column=3,
    )
    assert resolve(named, reports) is not None


# --- cell locator ------------------------------------------------------------------------


def test_a_cell_locator_finds_the_value(reports: dict[ReportKind, ReportDocument]) -> None:
    named = _billing(kind="cell", cell="B2", label="")
    assert resolve(named, reports) is not None


def test_a_cell_locator_is_case_insensitive(reports: dict[ReportKind, ReportDocument]) -> None:
    assert resolve(_billing(kind="cell", cell="b2", label=""), reports) is not None


def test_an_out_of_range_cell_resolves_to_none(reports: dict[ReportKind, ReportDocument]) -> None:
    assert resolve(_billing(kind="cell", cell="Z999", label=""), reports) is None


def test_a_malformed_cell_address_resolves_to_none(
    reports: dict[ReportKind, ReportDocument],
) -> None:
    assert resolve(_billing(kind="cell", cell="not-an-address", label=""), reports) is None


# --- missing report or sheet ----------------------------------------------------------------


def test_a_missing_report_resolves_to_none(reports: dict[ReportKind, ReportDocument]) -> None:
    assert resolve(_billing(report_kind="cross_tab"), reports) is None


def test_a_missing_sheet_resolves_to_none(reports: dict[ReportKind, ReportDocument]) -> None:
    assert resolve(_billing(sheet="Nope"), reports) is None


def test_resolve_all_maps_unresolvable_names_to_none_rather_than_omitting_them(
    reports: dict[ReportKind, ReportDocument],
) -> None:
    """The evaluator has to be able to name exactly what was missing."""
    values = resolve_all([_billing(), _billing(name="ghost", label="Nope")], reports)
    assert set(values) == {"billing_count", "ghost"}
    assert values["ghost"] is None


# --- number coercion -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1204, 1204.0),
        (12.5, 12.5),
        ("1,204", 1204.0),
        ("$40,000", 40000.0),
        ("18.2%", 0.182),
        ("  7 ", 7.0),
    ],
)
def test_report_cells_coerce_to_numbers(value: object, expected: float) -> None:
    assert to_number(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["Total rows", "", None, True])
def test_non_numeric_cells_coerce_to_none(value: object) -> None:
    """A label or a flag is not a number; treating it as one would fabricate a result."""
    assert to_number(value) is None
