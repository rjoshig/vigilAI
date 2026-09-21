"""A delivery whose layout is not what the checks ship with (Phase 6.21a).

This is the phase's first acceptance criterion, made testable. The ``layout_drift``
fixture is the baseline case — a delivery with nothing wrong with it — written by a
customer who names their sheets, headers and totals differently:

======================  =========================
the fixed checks ask    the delivery writes
======================  =========================
``Attributes``          ``Attribute Summary``
``Attribute``           ``Attribute Name``
``States``              ``State Breakdown``
``State``               ``State Code``
``Fields``              ``Field Values``
``Flow``                ``Record Flow``
``Accepts``             ``Accepted total``
``Rejects``             ``Rejected total``
======================  =========================

Before this phase every check that needed one of those returned ``passed=None`` and
became a "could not evaluate" finding. The run was honest — the finalize gate would not
let anybody freeze a report over it — and it validated nothing, which is the state a
reviewer meets on their first real delivery.

The tests below are the before and the after. ``test_*_without_the_ladder`` uses the
pre-6.21 rule directly, so the regression they guard against is visible rather than
remembered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from greenlight_ai.checks.reports import attribute_stats, run_derived_check
from greenlight_ai.llm.prompts.schemas import NameLocation
from greenlight_ai.parsers.base import ReportDocument, ReportKind
from greenlight_ai.parsers.reports.xlsx import parser_for
from greenlight_ai.resolve.layout import LayoutResolver, alternates_key
from greenlight_ai.rules.derive import DerivedCheck

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _reports(case: str) -> dict[ReportKind, ReportDocument]:
    """Parse every report of one fixture case."""
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    entry = next(c for c in manifest["cases"] if c["name"] == case)
    return {
        kind: parser_for(kind).parse(FIXTURES / path)
        for kind, path in entry["reports"].items()
        if kind in ("dirt", "state_distribution", "field_distribution", "counts")
    }


@pytest.fixture(scope="module")
def drifted() -> dict[ReportKind, ReportDocument]:
    return _reports("layout_drift")


class _Client:
    """Answers the name locator as a competent model would, and counts the asking.

    Keyed on the description the prompt ends with rather than on anything that appears
    anywhere in it: the built-in worked examples name ``Accepts`` too, and a fake that
    matched those would answer every call the same way and prove nothing.
    """

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def complete(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        self.asked.append(user)
        question = user.rsplit("Looking for: ", 1)[-1].splitlines()[0]
        found = next((v for k, v in self.answers.items() if k in question), "")

        class _Result:
            def parsed(self, _schema: Any) -> Any:
                return NameLocation(
                    verdict="found" if found else "absent",
                    name=found,
                    reason="read from the names offered",
                    confidence=0.9 if found else 0.1,
                )

        return _Result()


#: What the fake answers, keyed by a phrase only that name's description carries
#: (``checks.reports.WHAT``).
FLOW_TOTALS = {
    "passed every filter": "Accepted total",
    "filtered out": "Rejected total",
}


# --------------------------------------------------------------------------- before


def test_the_drifted_sheets_are_invisible_to_the_old_rule(
    drifted: dict[ReportKind, ReportDocument],
) -> None:
    """Lowercase, strip, compare — which is what every caller did before 6.21."""
    names = {n.strip().lower() for n in drifted["dirt"].sheet_names}
    assert "attributes" not in names
    assert "attribute summary" in names


def test_nothing_is_checkable_without_the_ladder(drifted: dict[ReportKind, ReportDocument]) -> None:
    """The state this phase exists to end.

    A resolver whose only rung is exact equality — which is what the product had —
    cannot find the attribute sheet, so the DIRT yields no statistics at all.
    """
    exact_only = LayoutResolver()
    exact_only.name = lambda wanted, candidates, **kw: next(  # type: ignore[assignment]
        (None for c in candidates if c.strip().lower() == wanted.strip().lower()), None
    )
    assert attribute_stats(drifted, None, exact_only) == {}


# ---------------------------------------------------------------------------- after


def test_the_ladder_reads_the_drifted_dirt(drifted: dict[ReportKind, ReportDocument]) -> None:
    """Both the sheet and the column it needs, in code, with no model call."""
    stats = attribute_stats(drifted, None, LayoutResolver())
    assert stats, "the attribute sheet and its heading both resolve deterministically"
    assert "score_v3" in {name.lower() for name in stats}


@pytest.mark.parametrize(
    "check",
    [
        DerivedCheck(kind="min_at_least", population="accepts", field_name="SCORE_V3", value=755.0),
        DerivedCheck(
            kind="value_set_subset", population="accepts", field_name="state", values=("IL", "AZ")
        ),
        DerivedCheck(
            kind="fields_present", population="accepts", field_name="", values=("SCORE_V3", "AGE")
        ),
    ],
)
def test_a_correct_delivery_passes_its_checks_despite_the_drift(
    drifted: dict[ReportKind, ReportDocument], check: DerivedCheck
) -> None:
    """The point of the whole phase.

    ``layout_drift`` *is* ``baseline_match``: there is nothing wrong with the delivery.
    Before 6.21 every one of these returned ``passed=None``; now each one runs and
    passes, with no model involved.
    """
    outcome = run_derived_check(check, drifted, None, LayoutResolver())
    assert outcome.passed is True, outcome.detail


def test_a_name_no_rung_reaches_still_says_so(drifted: dict[ReportKind, ReportDocument]) -> None:
    """Widening is not inventing.

    ``Accepts`` and ``Accepted`` share no token once the plural fold has run, so with
    no model the counts check cannot be evaluated — and it says that rather than
    guessing at a row.
    """
    check = DerivedCheck(kind="counts_reconcile", population="accepts", field_name="")
    outcome = run_derived_check(check, drifted, None, LayoutResolver())
    assert outcome.passed is None
    assert "accepts" in outcome.detail.lower()


def test_the_model_reaches_what_the_rungs_could_not(
    drifted: dict[ReportKind, ReportDocument],
) -> None:
    """The fifth rung, and the record it leaves behind."""
    client = _Client(FLOW_TOTALS)
    resolver = LayoutResolver(client=client)

    outcome = run_derived_check(
        DerivedCheck(kind="counts_reconcile", population="accepts", field_name=""),
        drifted,
        None,
        resolver,
    )
    assert outcome.passed is True, outcome.detail

    reached = {(r.wanted, r.found) for r in resolver.reasoned}
    assert reached == {("Accepts", "Accepted total"), ("Rejects", "Rejected total")}
    assert all(r.kind == "label" and r.confidence >= 0.6 for r in resolver.reasoned)


def test_the_expensive_rung_is_paid_for_once_per_name(
    drifted: dict[ReportKind, ReportDocument],
) -> None:
    """Two checks needing the same label is one call, not two."""
    client = _Client(FLOW_TOTALS)
    resolver = LayoutResolver(client=client)

    run_derived_check(
        DerivedCheck(kind="counts_reconcile", population="accepts", field_name=""),
        drifted,
        None,
        resolver,
    )
    before = len(client.asked)
    run_derived_check(
        DerivedCheck(kind="count_equals", population="accepts", field_name="", value=179_224.0),
        drifted,
        None,
        resolver,
    )
    assert len(client.asked) == before, "the second check reused the first's answer"


def test_a_layout_map_entry_removes_the_model_call_entirely(
    drifted: dict[ReportKind, ReportDocument],
) -> None:
    """What 6.21b buys: the second run of a known delivery is deterministic again."""
    client = _Client(FLOW_TOTALS)
    resolver = LayoutResolver(
        client=client,
        alternates={
            alternates_key("counts", "label", "Accepts"): ("Accepted total",),
            alternates_key("counts", "label", "Rejects"): ("Rejected total",),
        },
    )

    outcome = run_derived_check(
        DerivedCheck(kind="counts_reconcile", population="accepts", field_name=""),
        drifted,
        None,
        resolver,
    )
    assert outcome.passed is True
    assert client.asked == [], "nothing was asked of the model"
    assert resolver.reasoned == [], "and so nothing needs confirming"


def test_the_baseline_case_is_unaffected() -> None:
    """Nothing that matched before stops matching, on a real fixture rather than a unit."""
    reports = _reports("baseline_match")
    for resolver in (None, LayoutResolver()):
        outcome = run_derived_check(
            DerivedCheck(kind="counts_reconcile", population="accepts", field_name=""),
            reports,
            None,
            resolver,
        )
        assert outcome.passed is True, outcome.detail
