"""Coverage: what the run checked, and what it did not (Phase 6.11c).

The unit under test is pure code over a context, so these build contexts directly
rather than running a pipeline. The end-to-end behaviour lives in ``tests/api``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from greenlight_ai.llm.mock import MockClient
from greenlight_ai.pipeline import coverage as coverage_module
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.rules.schema import Condition, Rule, Trace


def _context() -> RunContext:
    """A bare context with no files, enough for coverage to read."""
    return RunContext(
        run_id="R1",
        osl_path=Path("osl.docx"),
        config_path=Path("config.json"),
        report_paths={},
        client=MockClient(),
    )


def _criteria(rule_id: str) -> Rule:
    """A criteria requirement, which a report check can answer."""
    return Rule(
        rule_id=rule_id,
        source="osl",
        req_type="criteria",
        conditions=(Condition(field_name="score", operator=">", value=755),),
        source_ref=f"OSL section {rule_id}",
        source_text="score above 755",
    )


def _other(rule_id: str) -> Rule:
    """A free-text requirement, which no check can express."""
    return Rule(
        rule_id=rule_id,
        source="osl",
        req_type="other",
        source_ref=f"OSL section {rule_id}",
        source_text="Handle edge cases sensibly.",
    )


def _traced(rule_id: str) -> Trace:
    """A trace that links a requirement to an element."""
    return Trace(rule_id=rule_id, element_id="E-1", verdict="implemented", confidence=0.9)


def test_a_requirement_a_check_answered_is_checked() -> None:
    context = _context()
    context.rules = [_criteria("R-1")]
    context.traces = [_traced("R-1")]
    context.coverage_record.checked("R-1", "dirt")

    entry = coverage_module.compute(context).requirements[0]

    assert entry.state == "checked"
    assert entry.osl_ref == "OSL section R-1"


def test_a_traced_requirement_no_check_reached_is_traced_unchecked() -> None:
    context = _context()
    context.rules = [_criteria("R-1")]
    context.traces = [_traced("R-1")]

    coverage = coverage_module.compute(context)

    assert coverage.requirements[0].state == "traced_unchecked"
    assert coverage.counts["traced_unchecked"] == 1
    assert [e.rule_id for e in coverage.unresolved] == ["R-1"]


def test_a_requirement_nothing_implements_is_untraced() -> None:
    context = _context()
    context.rules = [_criteria("R-1")]

    coverage = coverage_module.compute(context)

    assert coverage.requirements[0].state == "untraced"
    # Already a finding of its own from stage 5, so not a second acknowledgement.
    assert coverage.unresolved == ()


def test_a_free_text_requirement_is_manual() -> None:
    context = _context()
    context.rules = [_other("R-1")]
    context.traces = [_traced("R-1")]

    coverage = coverage_module.compute(context)

    assert coverage.requirements[0].state == "manual"
    assert [e.rule_id for e in coverage.unresolved] == ["R-1"]


def test_a_check_that_could_not_be_evaluated_leaves_the_requirement_manual() -> None:
    """The delivery was compared against nothing, whatever the check intended."""
    context = _context()
    context.rules = [_criteria("R-1")]
    context.traces = [_traced("R-1")]
    context.coverage_record.unevaluated("R-1")

    assert coverage_module.compute(context).requirements[0].state == "manual"


def test_one_answered_check_covers_a_requirement_another_could_not_evaluate() -> None:
    """A requirement checked against one report is covered, not manual."""
    context = _context()
    context.rules = [_criteria("R-1")]
    context.traces = [_traced("R-1")]
    context.coverage_record.unevaluated("R-1")
    context.coverage_record.checked("R-1", "dirt")

    assert coverage_module.compute(context).requirements[0].state == "checked"


def test_a_trace_to_nothing_is_not_a_trace() -> None:
    context = _context()
    context.rules = [_criteria("R-1")]
    context.traces = [Trace(rule_id="R-1", element_id=None, verdict="not_related", confidence=0.2)]

    assert coverage_module.compute(context).requirements[0].state == "untraced"


def test_counts_name_every_state_even_at_zero() -> None:
    context = _context()
    context.rules = [_criteria("R-1")]
    context.coverage_record.checked("R-1", "dirt")

    assert coverage_module.compute(context).counts == {
        "checked": 1,
        "traced_unchecked": 0,
        "untraced": 0,
        "manual": 0,
    }


def test_the_record_is_cleared_so_a_recheck_does_not_double_count() -> None:
    record = coverage_module.CoverageRecord()
    record.checked("R-1", "dirt")
    record.unevaluated("R-2")

    record.clear()

    assert record.checked_rule_ids == set()
    assert record.unevaluated_rule_ids == set()
    assert record.checks_by_report == {}


def test_a_check_with_no_requirement_still_counts_towards_its_report() -> None:
    """An admin check or a field constraint covers a report without naming a rule."""
    record = coverage_module.CoverageRecord()
    record.checked("", "billing")

    assert record.checks_by_report == {"billing": 1}
    assert record.checked_rule_ids == set()


def test_storage_round_trips() -> None:
    context = _context()
    context.rules = [_criteria("R-1"), _other("R-2")]
    context.traces = [_traced("R-1"), _traced("R-2")]
    context.coverage_record.checked("R-1", "dirt")
    original = coverage_module.compute(context)

    restored = coverage_module.from_rows(
        coverage_module.as_rows(original),
        [{"kind": "dirt", "checks_applied": 1}],
        ["a notice"],
    )

    assert [e.state for e in restored.requirements] == ["checked", "manual"]
    assert restored.reports[0].checks_applied == 1
    assert restored.notices == ("a notice",)


@pytest.mark.parametrize("bad", [{"state": "nonsense"}, {}, {"state": None}])
def test_a_row_that_no_longer_parses_is_left_out_rather_than_raising(bad: dict) -> None:
    """A malformed stored row must not stop a reviewer opening the run."""
    assert coverage_module.from_rows([bad]).requirements == ()


def test_a_stored_count_that_is_not_a_number_reads_as_zero() -> None:
    restored = coverage_module.from_rows([], [{"kind": "dirt", "checks_applied": "many"}])

    assert restored.reports[0].checks_applied == 0
    assert restored.unchecked_reports == ("dirt",)
