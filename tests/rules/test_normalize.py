"""Tests for the normalizers."""

from __future__ import annotations

import pytest

from greenlight_ai.rules import (
    STATE_CODES,
    AliasTable,
    Interval,
    interval_from_condition,
    normalize_field_name,
    normalize_state,
    normalize_states,
    parse_number,
)

# --- states ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Illinois", "IL"), ("illinois", "IL"), ("  Arizona  ", "AZ"), ("IL", "IL"), ("az", "AZ")],
)
def test_state_names_and_codes_normalise(value: str, expected: str) -> None:
    assert normalize_state(value) == expected


@pytest.mark.parametrize("value", ["Atlantis", "ZZ", "", "   "])
def test_unrecognised_states_return_none(value: str) -> None:
    assert normalize_state(value) is None


def test_district_and_territories_are_covered() -> None:
    assert normalize_state("District of Columbia") == "DC"
    assert normalize_state("Puerto Rico") == "PR"


def test_all_codes_are_two_uppercase_letters() -> None:
    for code in STATE_CODES.values():
        assert len(code) == 2 and code.isupper()


def test_unrecognised_states_are_returned_not_dropped() -> None:
    """Silently dropping a bad state would hide a finding."""
    codes, unrecognised = normalize_states(["Illinois", "TX", "Atlantis"])
    assert codes == frozenset({"IL", "TX"})
    assert unrecognised == ("Atlantis",)


def test_duplicate_states_collapse() -> None:
    codes, _ = normalize_states(["IL", "Illinois", "il"])
    assert codes == frozenset({"IL"})


# --- field names -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("SCORE_V3", "score_v3"),
        ("V3 score", "v3_score"),
        ("V3-Score", "v3_score"),
        ("  revolving   utilization  ", "revolving_utilization"),
        ("Score (V3)", "score_v3"),
    ],
)
def test_field_names_reduce_to_a_comparable_form(value: str, expected: str) -> None:
    assert normalize_field_name(value) == expected


# --- aliases ---------------------------------------------------------------------------


@pytest.fixture()
def aliases() -> AliasTable:
    return AliasTable.from_mapping(
        {
            "score": ["SCORE_V3", "V3 score", "credit score"],
            "revolving_utilization": ["REV_UTIL", "utilization"],
        }
    )


def test_aliases_resolve_to_the_canonical_name(aliases: AliasTable) -> None:
    for name in ("SCORE_V3", "V3 score", "V3-SCORE", "credit score"):
        assert aliases.resolve(name) == "score"


def test_canonical_name_resolves_to_itself(aliases: AliasTable) -> None:
    assert aliases.resolve("score") == "score"


def test_unknown_name_stays_visible_rather_than_raising(aliases: AliasTable) -> None:
    """An unknown attribute must fail to match and become a finding, not an exception."""
    assert aliases.resolve("Mystery Field") == "mystery_field"
    assert not aliases.knows("Mystery Field")


def test_knows_reports_membership(aliases: AliasTable) -> None:
    assert aliases.knows("REV_UTIL")


# --- numbers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (755, 755.0),
        (755.5, 755.5),
        ("755", 755.0),
        ("1,000,000", 1_000_000.0),
        ("$40,000", 40_000.0),
        ("60%", 0.6),
        ("  21  ", 21.0),
        ("-5", -5.0),
    ],
)
def test_numbers_are_read_from_the_forms_specs_use(value: object, expected: float) -> None:
    assert parse_number(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["no digits here", "", None])
def test_unreadable_numbers_raise(value: object) -> None:
    with pytest.raises(ValueError, match="no number found"):
        parse_number(value)


def test_booleans_are_not_numbers() -> None:
    """True == 1 in Python; accepting it would silently turn a flag into a threshold."""
    with pytest.raises(ValueError, match="boolean"):
        parse_number(True)


# --- intervals ---------------------------------------------------------------------------


def test_inclusive_and_exclusive_bounds_stay_distinguishable() -> None:
    """Operator mismatch is its own finding type, so >= and > must not collapse."""
    inclusive = interval_from_condition(">=", 21)
    exclusive = interval_from_condition(">", 21)
    assert inclusive is not None and exclusive is not None
    assert inclusive != exclusive
    assert inclusive.same_bounds_as(exclusive)


def test_interval_contains_respects_inclusivity() -> None:
    inclusive = Interval(lower=21, lower_inclusive=True)
    exclusive = Interval(lower=21, lower_inclusive=False)
    assert inclusive.contains(21) and not exclusive.contains(21)
    assert inclusive.contains(22) and exclusive.contains(22)


def test_upper_bounds_respect_inclusivity() -> None:
    assert Interval(upper=0.6, upper_inclusive=False).contains(0.599)
    assert not Interval(upper=0.6, upper_inclusive=False).contains(0.6)
    assert Interval(upper=0.6, upper_inclusive=True).contains(0.6)


def test_unbounded_intervals_accept_everything_on_that_side() -> None:
    assert Interval(lower=21).contains(1e9)
    assert Interval().contains(0)


def test_between_becomes_a_closed_interval() -> None:
    interval = interval_from_condition("between", [700, 800])
    assert interval == Interval(lower=700, upper=800)
    assert interval is not None and interval.contains(700) and interval.contains(800)


def test_equality_becomes_a_point_interval() -> None:
    interval = interval_from_condition("=", 50)
    assert interval is not None
    assert interval.contains(50) and not interval.contains(51)


def test_set_operators_have_no_interval() -> None:
    assert interval_from_condition("in", ["IL"]) is None
    assert interval_from_condition("is_null", None) is None


def test_between_with_wrong_arity_raises() -> None:
    with pytest.raises(ValueError, match="exactly two bounds"):
        interval_from_condition("between", [700])


def test_percentage_conditions_normalise() -> None:
    interval = interval_from_condition("<", "60%")
    assert interval == Interval(upper=0.6, upper_inclusive=False)


@pytest.mark.parametrize(
    ("interval", "text"),
    [
        (Interval(lower=21), "[21, ∞)"),
        (Interval(upper=0.6, upper_inclusive=False), "(-∞, 0.6)"),
        (Interval(lower=700, upper=800), "[700, 800]"),
    ],
)
def test_intervals_render_in_standard_notation(interval: Interval, text: str) -> None:
    assert str(interval) == text
