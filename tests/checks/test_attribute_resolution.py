"""An unresolved attribute name is not a violation (Phase 6.22a).

`checks/reports.py` answered "does the DIRT carry this attribute?" in two places and
gave two different answers when it did not know. `_check_fields_present` called it a
**high-severity violation**; `_check_bound`, for the very same miss, called it *could
not evaluate*. `checks/field_constraints.py` held a third copy of the same test.

These tests pin the repair from both ends: the honest answer on a correct delivery, and
the unchanged answer on a defective one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from greenlight_ai.checks.field_constraints import FieldConstraintSpec
from greenlight_ai.checks.field_constraints import evaluate as evaluate_constraints
from greenlight_ai.checks.reports import run_derived_check
from greenlight_ai.parsers import parser_for
from greenlight_ai.parsers.base import ReportDocument, ReportKind
from greenlight_ai.rules.derive import DerivedCheck
from greenlight_ai.rules.normalize import AliasTable

#: What the OSL of the ``attribute_renamed`` fixture asks for.
ASKED = ("SCORE_V3", "AGE", "ST", "REV_UTIL", "OPEN_TRADES")


def _reports(root: Path, case: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    return {
        kind: parser_for(kind).parse(root / path)  # type: ignore[arg-type]
        for kind, path in case["reports"].items()
    }


@pytest.fixture()
def renamed(fixtures_root: Path, cases: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    """A correct delivery whose DIRT spells every attribute the long way."""
    return _reports(fixtures_root, cases["attribute_renamed"])


@pytest.fixture()
def short_one(fixtures_root: Path, cases: dict[str, Any]) -> dict[ReportKind, ReportDocument]:
    """A delivery that really is missing an attribute."""
    return _reports(fixtures_root, cases["attributes_missing_in_report"])


def test_a_renamed_attribute_is_not_reported_as_missing(
    renamed: dict[ReportKind, ReportDocument],
) -> None:
    """The phase's first acceptance criterion, at the check level.

    Every attribute is present under another spelling, so the delivery satisfies the
    requirement. What the tool cannot do is prove it, and saying so is a review
    record — not a claim that the delivery is wrong.
    """
    check = DerivedCheck(
        rule_id="R1",
        kind="fields_present",
        population="accepts",
        description="the requested attributes",
        values=ASKED,
    )
    outcome = run_derived_check(check, renamed)
    assert outcome.passed is not False, outcome.detail
    assert set(outcome.unresolved) == set(ASKED)
    assert "not counted as missing" in outcome.detail


def test_an_attribute_that_was_not_delivered_is_still_a_violation(
    short_one: dict[ReportKind, ReportDocument],
) -> None:
    """The regression guard.

    ``INCOME_EST`` is genuinely absent. Widening what counts as "cannot tell" must not
    soften a real defect, or the repair would trade a false positive for the far worse
    false negative.
    """
    check = DerivedCheck(
        rule_id="R2",
        kind="fields_present",
        population="accepts",
        description="the requested attributes",
        values=("SCORE_V3", "INCOME_EST"),
    )
    outcome = run_derived_check(check, short_one)
    assert outcome.passed is False
    assert "INCOME_EST" in outcome.detail
    assert outcome.unresolved == ()


def test_both_check_paths_agree_about_one_unmatched_name(
    renamed: dict[ReportKind, ReportDocument],
) -> None:
    """The defect that made this phase necessary: two answers to one question.

    ``fields_present`` and a bound check are asked about the same attribute in the same
    report. Before the shared helper one called it a high-severity violation and the
    other called it unevaluated.
    """
    fields = run_derived_check(
        DerivedCheck(
            rule_id="R3",
            kind="fields_present",
            population="accepts",
            description="attributes",
            values=("SCORE_V3",),
        ),
        renamed,
    )
    bound = run_derived_check(
        DerivedCheck(
            rule_id="R4",
            kind="min_at_least",
            population="accepts",
            description="the score floor",
            field_name="SCORE_V3",
            value=700,
        ),
        renamed,
    )
    assert fields.passed is None
    assert bound.passed is None
    assert fields.unresolved == bound.unresolved == ("SCORE_V3",)


def test_a_field_constraint_uses_the_same_helper(
    renamed: dict[ReportKind, ReportDocument],
) -> None:
    """The third copy of the test, now sharing the path.

    ``OPEN_TRADES`` is named as a row in the attribute sheet and is a column nowhere,
    so no report carries it and the constraint reports that it could not be checked —
    never silence. ``SCORE_V3`` would be the wrong choice here: the DIRT's sample tab
    carries it verbatim as a column, so it would match for a reason that has nothing
    to do with this repair.
    """
    spec = FieldConstraintSpec(id=1, field="OPEN_TRADES", constraint="not_blank", value=None)
    outcomes = evaluate_constraints([spec], renamed, AliasTable.from_mapping({}))
    assert [outcome.passed for outcome in outcomes] == [None]


def test_a_constraint_still_matches_a_plainly_named_column(
    short_one: dict[ReportKind, ReportDocument],
) -> None:
    """Nothing that matched before the shared helper stops matching.

    A field constraint looks for a *column* carrying the attribute. ``SCORE_V3`` is one
    on the DIRT's sample tab, which this fixture spells plainly, so it resolves exactly
    as it did before the shared helper existed.
    """
    spec = FieldConstraintSpec(id=2, field="SCORE_V3", constraint="not_blank", value=None)
    outcomes = evaluate_constraints([spec], short_one, AliasTable.from_mapping({}))
    assert any(outcome.passed is not None for outcome in outcomes)
