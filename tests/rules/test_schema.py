"""Tests for the canonical rule schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from greenlight_ai.rules import (
    LOW_CONFIDENCE,
    Condition,
    ConfigElement,
    Evidence,
    Finding,
    Rule,
    Trace,
)


def _criteria(**kwargs: object) -> Rule:
    base: dict[str, object] = {
        "rule_id": "R-001",
        "source": "osl",
        "req_type": "criteria",
        "conditions": [Condition(field_name="score", operator=">=", value=755)],
    }
    base.update(kwargs)
    return Rule(**base)  # type: ignore[arg-type]


# --- Condition -------------------------------------------------------------------------


def test_condition_is_immutable() -> None:
    condition = Condition(field_name="score", operator=">=", value=755)
    with pytest.raises(ValidationError):
        condition.value = 750  # type: ignore[misc]


def test_null_operators_take_no_value() -> None:
    assert Condition(field_name="dob", operator="is_null").value is None
    with pytest.raises(ValidationError, match="takes no value"):
        Condition(field_name="dob", operator="is_null", value=1)


def test_comparison_operators_require_a_value() -> None:
    with pytest.raises(ValidationError, match="requires a value"):
        Condition(field_name="score", operator=">=")


def test_between_requires_exactly_two_bounds() -> None:
    assert Condition(field_name="score", operator="between", value=[700, 800])
    with pytest.raises(ValidationError, match="exactly two bounds"):
        Condition(field_name="score", operator="between", value=[700])


def test_in_requires_a_sequence() -> None:
    with pytest.raises(ValidationError, match="sequence of values"):
        Condition(field_name="state", operator="in", value="IL")


def test_unknown_operator_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition(field_name="score", operator="~=", value=1)  # type: ignore[arg-type]


# --- Rule ------------------------------------------------------------------------------


def test_criteria_requires_a_condition() -> None:
    with pytest.raises(ValidationError, match="at least one condition"):
        Rule(rule_id="R-1", source="osl", req_type="criteria")


@pytest.mark.parametrize("req_type", ["geography", "value_set", "attributes"])
def test_set_types_require_values_and_mode(req_type: str) -> None:
    with pytest.raises(ValidationError, match="requires 'values'"):
        Rule(rule_id="R-1", source="osl", req_type=req_type)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="requires 'mode'"):
        Rule(
            rule_id="R-1",
            source="osl",
            req_type=req_type,  # type: ignore[arg-type]
            values=("IL",),
        )


def test_waterfall_requires_two_steps() -> None:
    with pytest.raises(ValidationError, match="at least two steps"):
        Rule(rule_id="R-1", source="osl", req_type="waterfall", steps=("input",))


def test_quantity_requires_a_number() -> None:
    with pytest.raises(ValidationError, match="requires 'quantity'"):
        Rule(rule_id="R-1", source="osl", req_type="quantity")


def test_other_type_needs_no_payload() -> None:
    assert Rule(rule_id="R-1", source="osl", req_type="other").req_type == "other"


def test_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        _criteria(confidence=1.5)
    with pytest.raises(ValidationError):
        _criteria(confidence=-0.1)


def test_low_confidence_flag_uses_the_documented_threshold() -> None:
    assert _criteria(confidence=LOW_CONFIDENCE - 0.01).is_low_confidence
    assert not _criteria(confidence=LOW_CONFIDENCE).is_low_confidence


def test_unknown_field_is_rejected() -> None:
    """extra='forbid' stops a hallucinated key from passing validation silently."""
    with pytest.raises(ValidationError):
        _criteria(invented_key="x")


def test_lists_become_tuples() -> None:
    rule = Rule(
        rule_id="R-1", source="osl", req_type="geography", values=["IL", "AZ"], mode="include"
    )
    assert rule.values == ("IL", "AZ")


# --- ConfigElement ---------------------------------------------------------------------


def test_non_technical_element_requires_a_rule() -> None:
    with pytest.raises(ValidationError, match="requires a rule"):
        ConfigElement(element_id="C-1", json_path="filters[0]")


def test_technical_element_needs_no_rule() -> None:
    element = ConfigElement(element_id="C-1", json_path="logging", is_technical=True)
    assert element.rule is None


# --- Trace -----------------------------------------------------------------------------


def test_unlinked_trace_must_be_not_related() -> None:
    assert Trace(rule_id="R-1", verdict="not_related").element_id is None
    with pytest.raises(ValidationError, match="requires an element_id"):
        Trace(rule_id="R-1", verdict="implemented")


def test_code_linked_traces_are_marked() -> None:
    trace = Trace(rule_id="R-1", element_id="C-1", verdict="implemented", by_code=True)
    assert trace.by_code


# --- Finding ---------------------------------------------------------------------------


def _finding(**kwargs: object) -> Finding:
    base: dict[str, object] = {
        "finding_id": "F-01",
        "type": "value_mismatch",
        "severity": "high",
        "title": "Score threshold differs",
    }
    base.update(kwargs)
    return Finding(**base)  # type: ignore[arg-type]


def test_high_severity_finding_blocks_the_gate_until_decided() -> None:
    """ADR-015: every high-severity finding needs a decision."""
    assert _finding().needs_decision
    assert not _finding(review_status="confirmed").needs_decision
    assert not _finding(review_status="false_positive").needs_decision


def test_lower_severities_never_block_the_gate() -> None:
    for severity in ("medium", "low", "review"):
        assert not _finding(severity=severity).needs_decision


def test_evidence_carries_row_numbers_not_row_contents() -> None:
    """ADR-003: sample rows are referenced by number; contents never leave the parser."""
    evidence = Evidence(report_name="dirt.xlsx", sample_rows=(12, 44))
    assert evidence.sample_rows == (12, 44)
    assert "contents" not in Evidence.model_fields


def test_finding_records_the_rules_version_that_produced_it() -> None:
    assert _finding(rules_version=3).rules_version == 3
