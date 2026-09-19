"""Tests for the per-requirement-type report checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vigilai.checks.reports import REPORT_CHECKED_KINDS, attribute_stats, run_derived_check
from vigilai.parsers import parser_for
from vigilai.parsers.base import ReportDocument, ReportKind
from vigilai.rules.derive import DerivedCheck
from vigilai.rules.normalize import AliasTable

ALIASES = AliasTable.from_mapping(
    {
        "score": ["SCORE_V3"],
        "age": ["AGE"],
        "revolving_utilization": ["REV_UTIL", "revolving utilization"],
    }
)


def _reports(root: Path, case: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    return {
        kind: parser_for(kind).parse(root / path)  # type: ignore[arg-type]
        for kind, path in case["reports"].items()
    }


@pytest.fixture()
def clean(fixtures_root: Path, cases: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    return _reports(fixtures_root, cases["baseline_match"])


@pytest.fixture()
def low_score(fixtures_root: Path, cases: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    return _reports(fixtures_root, cases["score_value_mismatch"])


@pytest.fixture()
def broken_counts(fixtures_root: Path, cases: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    return _reports(fixtures_root, cases["counts_do_not_reconcile"])


# --- attribute statistics -------------------------------------------------------------


def test_attribute_stats_resolve_through_the_alias_table(
    clean: dict[ReportKind, ReportDocument],
) -> None:
    """The DIRT column is SCORE_V3; the OSL says "score"."""
    stats = attribute_stats(clean, ALIASES)
    assert "score" in stats
    assert stats["score"].name == "SCORE_V3"


def test_attribute_stats_are_empty_without_a_dirt() -> None:
    assert attribute_stats({}) == {}


def test_attribute_stats_carry_the_cell_address(clean: dict[ReportKind, ReportDocument]) -> None:
    assert attribute_stats(clean, ALIASES)["score"].address.startswith("A")


# --- bounds ---------------------------------------------------------------------------


def _bound(kind: str, field_name: str, value: float) -> DerivedCheck:
    return DerivedCheck(
        kind=kind,  # type: ignore[arg-type]
        population="accepts",
        field_name=field_name,
        value=value,
        rule_id="R-1",
        description=f"{field_name} {kind} {value}",
    )


def test_a_delivered_minimum_at_the_threshold_passes(
    clean: dict[ReportKind, ReportDocument],
) -> None:
    assert run_derived_check(_bound("min_at_least", "score", 755), clean, ALIASES).passed


def test_a_delivered_minimum_below_the_threshold_fails(
    low_score: dict[ReportKind, ReportDocument],
) -> None:
    outcome = run_derived_check(_bound("min_at_least", "score", 755), low_score, ALIASES)
    assert outcome.passed is False
    assert "750" in outcome.detail


def test_a_strict_minimum_rejects_the_boundary_value(
    clean: dict[ReportKind, ReportDocument],
) -> None:
    """The delivered minimum is exactly 755, which satisfies >= but not >."""
    assert (
        run_derived_check(_bound("min_greater_than", "score", 755), clean, ALIASES).passed is False
    )


def test_a_maximum_check_reads_the_max_column(clean: dict[ReportKind, ReportDocument]) -> None:
    assert run_derived_check(_bound("max_at_most", "age", 94), clean, ALIASES).passed
    assert run_derived_check(_bound("max_at_most", "age", 90), clean, ALIASES).passed is False


def test_an_unknown_attribute_cannot_be_evaluated(clean: dict[ReportKind, ReportDocument]) -> None:
    outcome = run_derived_check(_bound("min_at_least", "mystery", 1), clean, ALIASES)
    assert outcome.passed is None
    assert "does not appear" in outcome.detail


def test_a_bound_check_without_a_dirt_cannot_be_evaluated() -> None:
    assert run_derived_check(_bound("min_at_least", "score", 755), {}, ALIASES).passed is None


# --- value sets -----------------------------------------------------------------------


def _set_check(kind: str, values: tuple[str, ...]) -> DerivedCheck:
    return DerivedCheck(
        kind=kind,  # type: ignore[arg-type]
        population="accepts",
        field_name="state",
        values=values,
        rule_id="R-1",
        description="states",
    )


def test_an_allowed_state_set_passes(clean: dict[ReportKind, ReportDocument]) -> None:
    assert run_derived_check(_set_check("value_set_subset", ("IL", "AZ")), clean).passed


def test_an_unlisted_state_fails_and_is_named(fixtures_root: Path, cases: dict[str, Any]) -> None:
    reports = _reports(fixtures_root, cases["geography_extra_state"])
    outcome = run_derived_check(_set_check("value_set_subset", ("IL", "AZ")), reports)
    assert outcome.passed is False
    assert "TX" in outcome.detail and "NV" in outcome.detail


def test_an_exclude_list_passes_when_no_member_appears(
    clean: dict[ReportKind, ReportDocument],
) -> None:
    assert run_derived_check(_set_check("value_set_excludes", ("TX",)), clean).passed


def test_an_exclude_list_fails_when_a_member_appears(
    fixtures_root: Path, cases: dict[str, Any]
) -> None:
    reports = _reports(fixtures_root, cases["geography_extra_state"])
    outcome = run_derived_check(_set_check("value_set_excludes", ("TX",)), reports)
    assert outcome.passed is False


def test_a_missing_distribution_cannot_be_evaluated() -> None:
    assert run_derived_check(_set_check("value_set_subset", ("IL",)), {}).passed is None


# --- attributes present ---------------------------------------------------------------


def test_all_requested_attributes_present_passes(clean: dict[ReportKind, ReportDocument]) -> None:
    check = DerivedCheck(
        kind="fields_present",
        population="accepts",
        values=("SCORE_V3", "AGE"),
        rule_id="R-1",
        description="attributes",
    )
    assert run_derived_check(check, clean, ALIASES).passed


def test_a_missing_attribute_fails_and_is_named(clean: dict[ReportKind, ReportDocument]) -> None:
    check = DerivedCheck(
        kind="fields_present",
        population="accepts",
        values=("SCORE_V3", "NOT_DELIVERED"),
        rule_id="R-1",
        description="attributes",
    )
    outcome = run_derived_check(check, clean, ALIASES)
    assert outcome.passed is False
    assert "NOT_DELIVERED" in outcome.detail


# --- counts ---------------------------------------------------------------------------


def _counts(kind: str, value: float | None = None) -> DerivedCheck:
    return DerivedCheck(
        kind=kind,  # type: ignore[arg-type]
        population="all",
        value=value,
        rule_id="R-1",
        description="counts",
    )


def test_reconciling_counts_pass(clean: dict[ReportKind, ReportDocument]) -> None:
    assert run_derived_check(_counts("counts_reconcile"), clean).passed


def test_a_shortfall_fails_and_reports_the_difference(
    broken_counts: dict[ReportKind, ReportDocument],
) -> None:
    outcome = run_derived_check(_counts("counts_reconcile"), broken_counts)
    assert outcome.passed is False
    assert "-588" in outcome.detail


def test_counts_without_the_report_cannot_be_evaluated() -> None:
    assert run_derived_check(_counts("counts_reconcile"), {}).passed is None


def test_a_quantity_check_compares_the_accepts_total(
    clean: dict[ReportKind, ReportDocument], cases: dict[str, Any]
) -> None:
    accepts = cases["baseline_match"]["expected"]["accepts"]
    assert run_derived_check(_counts("count_equals", accepts), clean).passed
    assert run_derived_check(_counts("count_equals", accepts + 1), clean).passed is False


# --- scope ----------------------------------------------------------------------------


def test_step_order_is_not_a_report_check() -> None:
    """Order is settled between the OSL and the config in stage 5."""
    assert "step_order" not in REPORT_CHECKED_KINDS


def test_an_unhandled_kind_reports_that_it_cannot_be_evaluated(
    clean: dict[ReportKind, ReportDocument],
) -> None:
    outcome = run_derived_check(_counts("step_order"), clean)
    assert outcome.passed is None
