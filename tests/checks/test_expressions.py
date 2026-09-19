"""Tests for the safe expression evaluator.

Check expressions arrive from a database row written by an admin, so they are untrusted
input. The escape tests matter as much as the arithmetic ones.
"""

from __future__ import annotations

import pytest

from vigilai.checks.expressions import (
    ExpressionError,
    UnresolvedValue,
    evaluate,
    referenced_names,
)

VALUES = {
    "billing_count": 178_636,
    "delivered_count": 178_636,
    "accepts_count": 178_636,
    "rejects_count": 821_364,
    "input_count": 1_000_000,
    "dirt_row_count": 178_640,
    "null_rate": 0.182,
}


# --- the checks from the design doc ------------------------------------------------------


def test_billing_not_above_delivered() -> None:
    assert evaluate("billing_count <= delivered_count", VALUES).passed


def test_billing_not_below_accepts() -> None:
    assert evaluate("billing_count >= accepts_count", VALUES).passed


def test_counts_add_up() -> None:
    assert evaluate("accepts_count + rejects_count == input_count", VALUES).passed


def test_a_failing_check_reports_false() -> None:
    assert not evaluate("dirt_row_count == accepts_count", VALUES).passed


def test_the_result_carries_the_values_used() -> None:
    """A failing check has to be able to show its inputs."""
    result = evaluate("dirt_row_count == accepts_count", VALUES)
    assert result.resolved == {"dirt_row_count": 178_640, "accepts_count": 178_636}


def test_only_the_names_used_are_reported() -> None:
    result = evaluate("billing_count > 0", VALUES)
    assert set(result.resolved) == {"billing_count"}


# --- arithmetic and comparison -------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 1 == 2", True),
        ("10 - 4 == 6", True),
        ("3 * 4 == 12", True),
        ("10 / 4 == 2.5", True),
        ("10 % 3 == 1", True),
        ("10 // 3 == 3", True),
        ("-5 < 0", True),
        ("+5 > 0", True),
        ("1 < 2 < 3", True),
        ("1 < 2 < 0", False),
        ("1 != 2", True),
        ("abs(-3) == 3", True),
        ("min(2, 9) == 2", True),
        ("max(2, 9) == 9", True),
        ("round(2.4) == 2", True),
        ("1 == 1 and 2 == 2", True),
        ("1 == 2 or 2 == 2", True),
    ],
)
def test_permitted_constructs(expression: str, expected: bool) -> None:
    assert evaluate(expression, {}).passed is expected


def test_percentages_compare_as_fractions() -> None:
    assert evaluate("null_rate < 0.2", VALUES).passed


def test_division_by_zero_is_reported_not_raised_as_zerodivision() -> None:
    with pytest.raises(ExpressionError, match="division by zero"):
        evaluate("1 / 0", {})


def test_comparing_a_number_with_a_label_is_an_authoring_error() -> None:
    with pytest.raises(ExpressionError, match="cannot compare"):
        evaluate("a < b", {"a": 1, "b": "Total rows"})


def test_arithmetic_on_a_label_is_an_authoring_error() -> None:
    with pytest.raises(ExpressionError, match="needs a number"):
        evaluate("a + b", {"a": 1, "b": "Total rows"})


def test_arithmetic_on_a_boolean_is_rejected() -> None:
    """True == 1 in Python; silently counting a flag as one would be worse than failing."""
    with pytest.raises(ExpressionError, match="boolean"):
        evaluate("a + 1", {"a": True})


# --- unresolved values ------------------------------------------------------------------------


def test_a_missing_name_is_reported_by_name() -> None:
    with pytest.raises(UnresolvedValue) as excinfo:
        evaluate("missing_value > 1", VALUES)
    assert excinfo.value.name == "missing_value"


def test_a_name_resolved_to_none_is_unresolved_not_zero() -> None:
    """A report cell that was not found is not a zero."""
    with pytest.raises(UnresolvedValue):
        evaluate("a > 1", {"a": None})


def test_unresolved_value_survives_pickling() -> None:
    import pickle

    restored = pickle.loads(pickle.dumps(UnresolvedValue("billing_count")))
    assert restored.name == "billing_count"


# --- the untrusted-input surface ------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os").system("ls")',
        'open("/etc/passwd").read()',
        "().__class__.__bases__",
        "a.__class__",
        "[1, 2, 3]",
        "{1: 2}",
        "(1, 2)",
        "lambda: 1",
        "a if a else a",
        "[x for x in range(3)]",
        "print(1)",
        "exec('1')",
        "globals()",
        "a := 1",
        "f'{a}'",
    ],
)
def test_constructs_outside_the_subset_are_refused(expression: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate(expression, {"a": 1})


def test_exponentiation_is_refused_because_it_is_a_one_character_dos() -> None:
    with pytest.raises(ExpressionError, match="Pow"):
        evaluate("2 ** 999999999", {})


def test_keyword_arguments_are_refused() -> None:
    with pytest.raises(ExpressionError, match="keyword"):
        evaluate("round(1.5, ndigits=1) == 1.5", {})


def test_a_syntax_error_names_the_problem() -> None:
    with pytest.raises(ExpressionError, match="not valid Python"):
        evaluate("a <", {"a": 1})


def test_an_unknown_function_is_refused_by_name() -> None:
    with pytest.raises(ExpressionError, match="'sqrt' is not allowed"):
        evaluate("sqrt(4) == 2", {})


# --- referenced names ----------------------------------------------------------------------------


def test_referenced_names_lists_the_named_values() -> None:
    assert referenced_names("billing_count <= delivered_count") == {
        "billing_count",
        "delivered_count",
    }


def test_referenced_names_excludes_permitted_functions() -> None:
    assert referenced_names("max(a, b) > 1") == {"a", "b"}


def test_referenced_names_rejects_a_malformed_expression() -> None:
    with pytest.raises(ExpressionError):
        referenced_names("a <")


# --- validation without running -------------------------------------------------------


def test_validate_returns_the_names_a_good_expression_uses() -> None:
    from vigilai.checks.expressions import validate

    assert validate("billing_count <= delivered_count") == {"billing_count", "delivered_count"}


@pytest.mark.parametrize(
    "expression",
    ['__import__("os").system("ls")', "open('/etc/passwd')", "2 ** 9", "[1,2]", "a.b"],
)
def test_validate_refuses_what_evaluate_would_refuse(expression: str) -> None:
    """Saving a dangerous check must fail now, not on the next run."""
    from vigilai.checks.expressions import validate

    with pytest.raises(ExpressionError):
        validate(expression)


def test_validate_catches_a_syntax_error() -> None:
    from vigilai.checks.expressions import validate

    with pytest.raises(ExpressionError, match="not valid Python"):
        validate("1 +")


def test_validate_catches_division_by_zero() -> None:
    from vigilai.checks.expressions import validate

    with pytest.raises(ExpressionError, match="division by zero"):
        validate("a / 0")
