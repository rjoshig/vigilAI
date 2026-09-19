"""Tests for validation guides (Phase 6.8b): rendering, examples, compilation."""

from __future__ import annotations

from greenlight_ai.checks.guides import (
    GuideEntry,
    GuideLocator,
    check_name,
    guide_lines,
    value_names,
)
from greenlight_ai.checks.named_values import config_value


def _entry(**fields: object) -> GuideEntry:
    return GuideEntry.model_validate(
        {
            "id": "accepts",
            "locator": {"kind": "label", "sheet": "Flow", "label": "Accepts", "value_column": 3},
            "meaning": "the delivered count",
            "osl_section": "2",
            "config_path": "input.count",
            "validate": "must equal the population",
            "comparison": "equals",
            **fields,
        }
    )


def test_guide_lines_are_short_and_carry_only_the_examples() -> None:
    entry = _entry(examples=[{"sample_id": 1, "label": "2025", "value": "179,224"}])
    lines = guide_lines("Counts", [entry])
    assert lines[0].startswith("Validation guide for Counts")
    assert "background" in lines[0]
    assert (
        lines[1] == "- Flow!Accepts: the delivered count; answers to OSL section 2, "
        "config input.count; check: must equal the population; e.g. 2025=179,224"
    )
    assert guide_lines("Counts", []) == ()


def test_an_entry_is_concrete_only_with_a_path_a_comparison_and_an_example() -> None:
    assert not _entry().is_concrete
    assert not _entry(comparison="", examples=[{"sample_id": 1}]).is_concrete
    assert not _entry(config_path="", examples=[{"sample_id": 1}]).is_concrete
    assert _entry(examples=[{"sample_id": 1, "value": "1"}]).is_concrete


def test_names_are_expression_safe_and_unique_per_type() -> None:
    entry = _entry(id="Accepts total!")
    assert value_names("counts", entry) == (
        "guide_counts_accepts_total",
        "guide_counts_accepts_total_config",
    )
    assert check_name("counts", entry) == "guide:counts:accepts_total"


def test_config_value_walks_dotted_paths_and_list_indexes() -> None:
    raw = {"input": {"count": 5}, "pipeline": {"steps": ["a", {"count": 7}]}}
    assert config_value(raw, "input.count") == 5
    assert config_value(raw, "pipeline.steps[1].count") == 7
    assert config_value(raw, "pipeline.steps[9]") is None
    assert config_value(raw, "nothing.here") is None


def test_the_wire_name_validate_maps_onto_the_field() -> None:
    entry = _entry()
    assert entry.validate_text == "must equal the population"
    assert entry.model_dump(by_alias=True)["validate"] == "must equal the population"
    assert GuideLocator().kind == "label"
