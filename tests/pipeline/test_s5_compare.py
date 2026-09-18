"""Direct tests for stage 5's comparisons.

The end-to-end tests cover the paths the synthetic cases reach; these cover every
comparison branch on its own, because stage 5 is where ADR-001 is actually honoured and
a wrong comparison is the worst failure this product can have.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vigilai.llm import LLMSettings, MockClient
from vigilai.pipeline.context import RunContext
from vigilai.pipeline.s5_compare import run as compare
from vigilai.rules.normalize import AliasTable
from vigilai.rules.schema import Condition, ConfigElement, Rule, Trace

ALIASES = AliasTable.from_mapping({"score": ["SCORE_V3"], "age": ["AGE"]})


def _context(rule: Rule, element_rule: Rule | None, verdict: str = "implemented") -> RunContext:
    """Build a context with one requirement already traced to one element."""
    context = RunContext(
        run_id="T",
        osl_path=Path("osl.docx"),
        config_path=Path("config.json"),
        report_paths={},
        client=MockClient(LLMSettings()),
        aliases=ALIASES,
    )
    context.rules = [rule]
    if element_rule is not None:
        context.elements = [
            ConfigElement(element_id="C-001", json_path="rules.x", rule=element_rule)
        ]
        context.traces = [
            Trace(
                rule_id=rule.rule_id,
                element_id="C-001",
                verdict=verdict,  # type: ignore[arg-type]
            )
        ]
    else:
        context.traces = [Trace(rule_id=rule.rule_id, verdict="not_related")]
    return context


def _criteria(rule_id: str, field_name: str, operator: str, value: float, **kw: object) -> Rule:
    condition = Condition(
        field_name=field_name,
        operator=operator,  # type: ignore[arg-type]
        value=value,
    )
    return Rule(
        rule_id=rule_id,
        source=kw.pop("source", "osl"),  # type: ignore[arg-type]
        req_type="criteria",
        conditions=[condition],
        **kw,  # type: ignore[arg-type]
    )


def _set_rule(rule_id: str, values: tuple[str, ...], mode: str = "include", **kw: object) -> Rule:
    return Rule(
        rule_id=rule_id,
        source=kw.pop("source", "osl"),  # type: ignore[arg-type]
        req_type="geography",
        values=values,
        mode=mode,  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def _types(context: RunContext) -> list[str]:
    return [f.type for f in context.findings]


# --- untraced requirements -------------------------------------------------------------


def test_an_untraced_requirement_is_high_severity() -> None:
    context = _context(_criteria("R-1", "score", ">=", 755), None)
    compare(context)
    assert _types(context) == ["rule_missing_in_config"]
    assert context.findings[0].severity == "high"


def test_a_low_confidence_extraction_is_flagged_for_review() -> None:
    rule = _criteria("R-1", "score", ">=", 755, confidence=0.5)
    context = _context(rule, _criteria("C-1", "SCORE_V3", ">=", 755, source="config"))
    compare(context)
    assert "low_confidence_extraction" in _types(context)
    flagged = next(f for f in context.findings if f.type == "low_confidence_extraction")
    assert flagged.severity == "review"


# --- criteria ----------------------------------------------------------------------------


def test_matching_criteria_produce_no_finding() -> None:
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "SCORE_V3", ">=", 755, source="config"),
    )
    compare(context)
    assert context.findings == []


def test_a_different_threshold_is_a_value_mismatch() -> None:
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "SCORE_V3", ">=", 750, source="config"),
    )
    compare(context)
    assert _types(context) == ["value_mismatch"]
    assert "755" in context.findings[0].title and "750" in context.findings[0].title


def test_the_same_threshold_with_a_different_operator_is_an_operator_mismatch() -> None:
    """A value mismatch and a boundary mismatch are different problems."""
    context = _context(
        _criteria("R-1", "age", ">=", 21),
        _criteria("C-1", "AGE", ">", 21, source="config"),
    )
    compare(context)
    assert _types(context) == ["operator_mismatch"]
    assert "exactly at 21" in context.findings[0].detail


def test_an_upper_bound_operator_difference_is_caught() -> None:
    context = _context(
        _criteria("R-1", "util", "<", 0.6),
        _criteria("C-1", "util", "<=", 0.6, source="config"),
    )
    compare(context)
    assert _types(context) == ["operator_mismatch"]


def test_a_condition_the_config_does_not_constrain_is_reported_missing() -> None:
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "AGE", ">=", 21, source="config"),
    )
    compare(context)
    assert _types(context) == ["rule_missing_in_config"]
    assert "score" in context.findings[0].title


def test_aliases_are_resolved_before_comparing() -> None:
    """SCORE_V3 and score are the same attribute; a missing alias would be a false finding."""
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "SCORE_V3", ">=", 755, source="config"),
    )
    compare(context)
    assert context.findings == []


def test_a_set_operator_difference_with_no_interval_is_still_reported() -> None:
    rule = Rule(
        rule_id="R-1",
        source="osl",
        req_type="criteria",
        conditions=[Condition(field_name="score", operator="in", value=[1, 2])],
    )
    other = Rule(
        rule_id="C-1",
        source="config",
        req_type="criteria",
        conditions=[Condition(field_name="SCORE_V3", operator="not_in", value=[1, 2])],
    )
    context = _context(rule, other)
    compare(context)
    assert _types(context) == ["operator_mismatch"]


# --- sets ---------------------------------------------------------------------------------


def test_matching_sets_produce_no_finding() -> None:
    context = _context(
        _set_rule("R-1", ("IL", "AZ")), _set_rule("C-1", ("AZ", "IL"), source="config")
    )
    compare(context)
    assert context.findings == []


def test_an_extra_member_is_medium_and_names_the_member() -> None:
    context = _context(
        _set_rule("R-1", ("IL", "AZ")), _set_rule("C-1", ("IL", "AZ", "TX"), source="config")
    )
    compare(context)
    assert _types(context) == ["extra_rule_in_config"]
    assert "TX" in context.findings[0].detail
    assert context.findings[0].severity == "medium"


def test_a_missing_member_is_high_and_names_the_member() -> None:
    context = _context(_set_rule("R-1", ("IL", "AZ")), _set_rule("C-1", ("IL",), source="config"))
    compare(context)
    assert _types(context) == ["rule_missing_in_config"]
    assert "AZ" in context.findings[0].detail
    assert context.findings[0].severity == "high"


def test_both_directions_are_reported_separately() -> None:
    context = _context(
        _set_rule("R-1", ("IL", "AZ")), _set_rule("C-1", ("IL", "TX"), source="config")
    )
    compare(context)
    assert set(_types(context)) == {"rule_missing_in_config", "extra_rule_in_config"}


def test_an_inverted_mode_is_reported_before_the_members() -> None:
    """Same values with include vs exclude means the opposite thing, so it leads."""
    context = _context(
        _set_rule("R-1", ("IL", "AZ")),
        _set_rule("C-1", ("IL", "AZ"), mode="exclude", source="config"),
    )
    compare(context)
    assert _types(context) == ["operator_mismatch"]
    assert "opposite" in context.findings[0].detail


# --- waterfall ------------------------------------------------------------------------------


def _waterfall(rule_id: str, steps: tuple[str, ...], source: str = "osl") -> Rule:
    return Rule(
        rule_id=rule_id,
        source=source,  # type: ignore[arg-type]
        req_type="waterfall",
        steps=steps,
    )


def test_identical_step_order_produces_no_finding() -> None:
    steps = ("geography", "score", "age")
    context = _context(_waterfall("R-1", steps), _waterfall("C-1", steps, "config"))
    compare(context)
    assert context.findings == []


def test_extra_config_steps_are_left_to_the_reverse_pass() -> None:
    """A config lists boundary steps the OSL never mentions, such as the input step."""
    context = _context(
        _waterfall("R-1", ("geography", "score")),
        _waterfall("C-1", ("input", "geography", "score", "dedupe"), "config"),
    )
    compare(context)
    assert context.findings == []


def test_a_step_the_osl_requires_but_the_config_lacks_is_reported() -> None:
    context = _context(
        _waterfall("R-1", ("geography", "score", "exclusions")),
        _waterfall("C-1", ("geography", "score"), "config"),
    )
    compare(context)
    assert _types(context) == ["rule_missing_in_config"]
    assert "exclusions" in context.findings[0].detail


def test_reordered_shared_steps_are_an_order_mismatch() -> None:
    context = _context(
        _waterfall("R-1", ("geography", "score", "age")),
        _waterfall("C-1", ("input", "score", "geography", "age"), "config"),
    )
    compare(context)
    assert _types(context) == ["waterfall_order_mismatch"]
    assert context.findings[0].severity == "high"


def test_step_names_are_compared_case_insensitively() -> None:
    context = _context(
        _waterfall("R-1", ("Geography", "Score")),
        _waterfall("C-1", ("geography", "score"), "config"),
    )
    compare(context)
    assert context.findings == []


# --- quantity ---------------------------------------------------------------------------------


def _quantity(rule_id: str, amount: float, source: str = "osl") -> Rule:
    return Rule(
        rule_id=rule_id,
        source=source,  # type: ignore[arg-type]
        req_type="quantity",
        quantity=amount,
    )


def test_a_matching_quantity_produces_no_finding() -> None:
    context = _context(_quantity("R-1", 50_000), _quantity("C-1", 50_000, "config"))
    compare(context)
    assert context.findings == []


def test_a_differing_quantity_is_a_value_mismatch() -> None:
    context = _context(_quantity("R-1", 50_000), _quantity("C-1", 40_000, "config"))
    compare(context)
    assert _types(context) == ["value_mismatch"]


# --- evidence ------------------------------------------------------------------------------------


def test_every_finding_carries_osl_and_config_evidence() -> None:
    rule = _criteria("R-1", "score", ">=", 755)
    rule = rule.model_copy(update={"source_ref": "OSL section 4", "source_text": "at least 755"})
    context = _context(rule, _criteria("C-1", "SCORE_V3", ">=", 750, source="config"))
    compare(context)
    evidence = context.findings[0].evidence
    assert evidence.osl_ref == "OSL section 4"
    assert evidence.osl_text == "at least 755"
    assert evidence.config_path == "rules.x"
    assert "755" not in evidence.config_value


def test_no_finding_detail_contains_a_row_value() -> None:
    """ADR-003: findings carry field names, thresholds, and paths only."""
    context = _context(
        _set_rule("R-1", ("IL", "AZ")), _set_rule("C-1", ("IL", "AZ", "TX"), source="config")
    )
    compare(context)
    for finding in context.findings:
        assert "SSN" not in finding.detail
        assert finding.evidence.sample_rows == ()


@pytest.mark.parametrize("verdict", ["not_related"])
def test_a_not_related_verdict_is_treated_as_missing(verdict: str) -> None:
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "SCORE_V3", ">=", 755, source="config"),
        verdict=verdict,
    )
    context.traces = [Trace(rule_id="R-1", verdict="not_related")]
    compare(context)
    assert _types(context) == ["rule_missing_in_config"]


# --- attribute names the alias table does not know yet ---------------------------------


def test_a_single_condition_pair_is_compared_even_without_an_alias() -> None:
    """Stage 4 already said these are the same subject; a phantom finding is worse."""
    empty = AliasTable.from_mapping({})
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "SCORE_V3", ">=", 750, source="config"),
    )
    context.aliases = empty
    compare(context)
    assert _types(context) == ["value_mismatch"]


def test_matching_values_under_different_names_produce_no_finding() -> None:
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "SCORE_V3", ">=", 755, source="config"),
    )
    context.aliases = AliasTable.from_mapping({})
    compare(context)
    assert context.findings == []


def test_a_known_attribute_with_no_counterpart_is_still_a_real_gap() -> None:
    """The fallback must not turn "score against age" into a value mismatch."""
    context = _context(
        _criteria("R-1", "score", ">=", 755),
        _criteria("C-1", "AGE", ">=", 21, source="config"),
    )
    compare(context)
    assert _types(context) == ["rule_missing_in_config"]


def test_several_conditions_still_need_the_alias_table() -> None:
    """With two on each side, pairing by position would be a guess, so it is not done."""
    rule = Rule(
        rule_id="R-1",
        source="osl",
        req_type="criteria",
        conditions=[
            Condition(field_name="score", operator=">=", value=755),
            Condition(field_name="age", operator=">=", value=21),
        ],
    )
    other = Rule(
        rule_id="C-1",
        source="config",
        req_type="criteria",
        conditions=[
            Condition(field_name="SCORE_V3", operator=">=", value=755),
            Condition(field_name="AGE", operator=">=", value=21),
        ],
    )
    context = _context(rule, other)
    context.aliases = AliasTable.from_mapping({})
    compare(context)
    # "age" and "AGE" normalise alike so they pair; "score" and "SCORE_V3" do not, and
    # with two conditions a side there is no safe way to guess, so it is reported.
    assert _types(context) == ["rule_missing_in_config"]
    assert "score" in context.findings[0].title
