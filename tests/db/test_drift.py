"""Tests for delivery drift: the pure comparisons (ADR-030)."""

from __future__ import annotations

from greenlight_ai.db import models
from greenlight_ai.db.drift import (
    describe_value,
    diff_config,
    diff_findings,
    diff_record_layout,
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


def _run_with_layout(*fields: tuple[str, str, str]) -> models.Run:
    """A run carrying a record layout snapshot of ``(name, type, size)`` triples."""
    return models.Run(
        customer_name="Northwind Credit Union",
        order_number="ORD-10018",
        configuration_id="CFG-SYNTH-LAYOUT-18",
        record_layout=[
            {"name": name, "data_type": data_type, "size": size, "ordinal": index}
            for index, (name, data_type, size) in enumerate(fields, start=1)
        ],
    )


class TestRecordLayoutDrift:
    """What changed in the shape of the delivered file itself (Phase 6.22b).

    The single most consequential change a delivery can carry and the one least likely
    to be mentioned: the findings list looks identical while a column has quietly
    become nine characters instead of ten.
    """

    def test_an_added_and_a_removed_field_are_both_named(self) -> None:
        previous = _run_with_layout(("SCORE_V3", "DECIMAL", "4"), ("OLD_FLAG", "CHAR", "1"))
        current = _run_with_layout(("SCORE_V3", "DECIMAL", "4"), ("NEW_FLAG", "CHAR", "1"))

        changes = diff_record_layout(current, previous)
        assert [(c.name, c.change) for c in changes] == [
            ("NEW_FLAG", "added"),
            ("OLD_FLAG", "removed"),
        ]

    def test_a_narrowed_field_is_a_resize_with_both_widths(self) -> None:
        """The case a reviewer would never find in the findings list."""
        previous = _run_with_layout(("ACCOUNT_NO", "CHAR", "10"))
        current = _run_with_layout(("ACCOUNT_NO", "CHAR", "9"))

        (change,) = diff_record_layout(current, previous)
        assert (change.change, change.before, change.after) == ("resized", "10", "9")

    def test_a_retyped_field_is_reported_once_not_twice(self) -> None:
        """A field that changed type and size is one edit, and is named once."""
        previous = _run_with_layout(("SCORE_V3", "CHAR", "4"))
        current = _run_with_layout(("SCORE_V3", "DECIMAL", "6"))

        (change,) = diff_record_layout(current, previous)
        assert (change.change, change.before, change.after) == ("retyped", "CHAR", "DECIMAL")

    def test_a_field_that_moved_position_is_reported(self) -> None:
        previous = _run_with_layout(("ST", "CHAR", "2"), ("AGE", "INT", "3"))
        current = _run_with_layout(("AGE", "INT", "3"), ("ST", "CHAR", "2"))

        assert {(c.name, c.change) for c in diff_record_layout(current, previous)} == {
            ("AGE", "moved"),
            ("ST", "moved"),
        }

    def test_a_respelled_field_is_not_one_removed_and_one_added(self) -> None:
        """Matched up the ladder, so separators are noise.

        Reporting ``opt_out`` becoming ``OPT-OUT`` as a field lost and a field gained
        would be the wrong answer, and the loud one.
        """
        previous = _run_with_layout(("opt_out", "CHAR", "1"))
        current = _run_with_layout(("OPT-OUT", "CHAR", "1"))
        assert diff_record_layout(current, previous) == ()

    def test_an_unchanged_layout_reports_nothing(self) -> None:
        previous = _run_with_layout(("SCORE_V3", "DECIMAL", "4"))
        current = _run_with_layout(("SCORE_V3", "DECIMAL", "4"))
        assert diff_record_layout(current, previous) == ()

    def test_a_delivery_with_no_layout_reports_nothing_rather_than_everything(self) -> None:
        """ "Unknown" is not "unchanged", and it is certainly not "every field removed"."""
        previous = _run_with_layout(("SCORE_V3", "DECIMAL", "4"))
        current = _run_with_layout()

        assert diff_record_layout(current, previous) == ()
        assert diff_record_layout(previous, current) == ()
