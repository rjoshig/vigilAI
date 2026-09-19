"""Tests for delivery drift: the pure comparisons (ADR-030)."""

from __future__ import annotations

from greenlight_ai.db import models
from greenlight_ai.db.drift import (
    describe_value,
    diff_config,
    diff_findings,
    diff_requirements,
    flatten,
)
from greenlight_ai.rules.schema import Condition, Rule


def _finding(title: str, status: str = "undecided", shadow: bool = False) -> models.Finding:
    return models.Finding(
        finding_id="F-01",
        type="value_mismatch",
        severity="high",
        title=title,
        leg="osl_config",
        review_status=status,
        shadow=shadow,
    )


def test_findings_are_matched_on_type_leg_and_title_and_shadow_ones_are_ignored() -> None:
    previous = [
        _finding("score: OSL says 755", "confirmed"),
        _finding("age gone", "false_positive"),
    ]
    current = [
        _finding("score: OSL says 755"),
        _finding("brand new"),
        _finding("hidden", shadow=True),
    ]
    new, resolved, carried = diff_findings(current, previous)
    assert [f.title for f in new] == ["brand new"]
    assert [f.title for f in resolved] == ["age gone"]
    assert [f.title for f in carried] == ["score: OSL says 755"]


def _rule(rule_id: str, req_type: str, ref: str, **fields: object) -> Rule:
    return Rule(  # type: ignore[arg-type]
        rule_id=rule_id, source="osl", req_type=req_type, source_ref=ref, **fields
    )


def test_requirements_are_matched_on_type_and_reference_not_on_number() -> None:
    previous = [
        _rule(
            "R-001",
            "criteria",
            "OSL 4",
            conditions=[Condition(field_name="score", operator=">=", value=750)],
        ),
        _rule("R-002", "geography", "OSL 3", values=["IL", "AZ"], mode="include"),
    ]
    current = [
        _rule(
            "R-007",
            "criteria",
            "OSL 4",
            conditions=[Condition(field_name="score", operator=">=", value=755)],
        ),
        _rule("R-008", "quantity", "OSL 2", quantity=1000),
    ]
    changes = {(c.source_ref, c.change): c for c in diff_requirements(current, previous)}
    assert changes[("OSL 4", "changed")].before == "score >= 750"
    assert changes[("OSL 4", "changed")].after == "score >= 755"
    assert changes[("OSL 2", "added")].after == "1000"
    assert changes[("OSL 3", "removed")].before == "AZ, IL"
    assert describe_value(_rule("R-1", "other", "x")) == ""


def test_config_diff_is_by_path_and_ignores_the_modified_stamp() -> None:
    previous = {
        "last_modified": "a",
        "rules": {"score": {"min": 750}},
        "output": {"fields": ["A", "B"]},
    }
    current = {
        "last_modified": "b",
        "rules": {"score": {"min": 755}, "age": {"min": 21}},
        "output": {"fields": ["A"]},
    }
    changes = {c.path: c for c in diff_config(current, previous)}
    assert set(changes) == {"rules.score.min", "rules.age.min", "output.fields[1]"}
    assert (changes["rules.score.min"].before, changes["rules.score.min"].after) == ("750", "755")
    assert changes["rules.age.min"].change == "added"
    assert changes["output.fields[1]"].change == "removed"
    assert diff_config(None, previous) == ()
    assert flatten({"a": [1, {"b": None}]}) == {"a[0]": 1, "a[1].b": None}
