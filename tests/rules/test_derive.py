"""Tests for derived report checks.

Derivations are fixed code per operator, never LLM output (ADR-001), so every operator
gets an explicit test.
"""

from __future__ import annotations

import pytest

from greenlight_ai.rules import Condition, Rule, derive_checks
from greenlight_ai.rules.product_codes import ProductCatalogue, ProductCodeEntry, ProductMember
from greenlight_ai.rules.derive import INVERSE_OPERATOR


def _criteria(operator: str, value: object, action: str = "accept", **kwargs: object) -> Rule:
    condition = Condition(
        field_name="age",
        operator=operator,  # type: ignore[arg-type]
        value=value,  # type: ignore[arg-type]
    )
    base: dict[str, object] = {
        "rule_id": "R-001",
        "source": "osl",
        "req_type": "criteria",
        "action": action,
        "conditions": [condition],
    }
    base.update(kwargs)
    return Rule(**base)  # type: ignore[arg-type]


# --- criteria --------------------------------------------------------------------------


def test_the_design_docs_worked_example() -> None:
    """age < 21 -> reject generates accepts.age.min >= 21."""
    checks = derive_checks(_criteria("<", 21, action="reject"))
    assert len(checks) == 1
    assert checks[0].kind == "min_at_least"
    assert checks[0].population == "accepts"
    assert checks[0].field_name == "age"
    assert checks[0].value == 21
    assert checks[0].description == "accepts.age.min >= 21"


@pytest.mark.parametrize(
    ("operator", "kind", "attribute"),
    [
        (">=", "min_at_least", "value"),
        (">", "min_greater_than", "value"),
        ("<=", "max_at_most", "value"),
        ("<", "max_less_than", "value"),
    ],
)
def test_every_range_operator_derives_its_bound(operator: str, kind: str, attribute: str) -> None:
    checks = derive_checks(_criteria(operator, 21))
    assert len(checks) == 1
    assert checks[0].kind == kind
    assert getattr(checks[0], attribute) == 21


def test_rejection_rules_invert_the_operator() -> None:
    accept = derive_checks(_criteria(">=", 21))[0]
    reject = derive_checks(_criteria(">=", 21, action="reject"))[0]
    assert accept.kind == "min_at_least"
    assert reject.kind == "max_less_than"


def test_inverse_table_is_symmetric() -> None:
    for operator, inverted in INVERSE_OPERATOR.items():
        assert INVERSE_OPERATOR[inverted] == operator


def test_between_derives_both_bounds() -> None:
    checks = derive_checks(_criteria("between", [700, 800]))
    assert {c.kind for c in checks} == {"min_at_least", "max_at_most"}
    assert {c.value for c in checks} == {700, 800}


def test_equality_derives_a_point() -> None:
    checks = derive_checks(_criteria("=", 50))
    assert {c.value for c in checks} == {50}


def test_null_checks_derive_nothing() -> None:
    assert derive_checks(_criteria("is_null", None)) == ()


def test_or_joined_conditions_derive_nothing() -> None:
    """Either branch may be satisfied, so neither bounds the delivered population."""
    rule = Rule(
        rule_id="R-1",
        source="osl",
        req_type="criteria",
        logic="OR",
        conditions=[
            Condition(field_name="age", operator=">=", value=21),
            Condition(field_name="score", operator=">=", value=755),
        ],
    )
    assert derive_checks(rule) == ()


def test_and_joined_conditions_derive_one_check_each() -> None:
    rule = Rule(
        rule_id="R-1",
        source="osl",
        req_type="criteria",
        conditions=[
            Condition(field_name="age", operator=">=", value=21),
            Condition(field_name="score", operator=">=", value=755),
        ],
    )
    assert {c.field_name for c in derive_checks(rule)} == {"age", "score"}


def test_unparseable_value_derives_nothing_rather_than_a_wrong_check() -> None:
    rule = _criteria(">=", "not a number")
    assert derive_checks(rule) == ()


def test_explicit_population_is_respected() -> None:
    checks = derive_checks(_criteria(">=", 21, applies_to="rejects"))
    assert checks[0].population == "rejects"


# --- sets ------------------------------------------------------------------------------


def test_include_list_becomes_a_subset_check() -> None:
    rule = Rule(
        rule_id="R-003", source="osl", req_type="geography", values=("IL", "AZ"), mode="include"
    )
    checks = derive_checks(rule)
    assert len(checks) == 1
    assert checks[0].kind == "value_set_subset"
    assert checks[0].field_name == "state"
    assert checks[0].values == ("IL", "AZ")


def test_exclude_list_becomes_an_excludes_check() -> None:
    rule = Rule(
        rule_id="R-004", source="osl", req_type="value_set", values=("X", "Y"), mode="exclude"
    )
    checks = derive_checks(rule)
    assert checks[0].kind == "value_set_excludes"
    assert checks[0].values == ("X", "Y")


def test_attributes_become_a_presence_check() -> None:
    rule = Rule(
        rule_id="R-011",
        source="osl",
        req_type="attributes",
        values=("SCORE_V3", "AGE"),
        mode="include",
    )
    checks = derive_checks(rule)
    assert len(checks) == 1
    assert checks[0].kind == "fields_present"
    assert checks[0].values == ("SCORE_V3", "AGE")


# --- waterfall and quantity -------------------------------------------------------------


def test_waterfall_derives_order_and_reconciliation() -> None:
    rule = Rule(
        rule_id="R-013",
        source="osl",
        req_type="waterfall",
        steps=("input", "geography", "score", "dedupe"),
    )
    checks = derive_checks(rule)
    assert {c.kind for c in checks} == {"step_order", "counts_reconcile"}
    order = next(c for c in checks if c.kind == "step_order")
    assert order.steps == ("input", "geography", "score", "dedupe")


def test_quantity_derives_a_count_check() -> None:
    rule = Rule(rule_id="R-020", source="osl", req_type="quantity", quantity=50_000)
    checks = derive_checks(rule)
    assert checks[0].kind == "count_equals"
    assert checks[0].value == 50_000


def test_free_text_requirements_derive_nothing() -> None:
    """An 'other' requirement is marked for manual verification, not auto-checked."""
    assert derive_checks(Rule(rule_id="R-1", source="osl", req_type="other")) == ()


def test_every_check_names_its_rule() -> None:
    rule = _criteria(">=", 21)
    for check in derive_checks(rule):
        assert check.rule_id == "R-001"


class TestProductCodes:
    """A requirement that names a code derives the same check as one that lists (6.22c)."""

    def _catalogue(self) -> ProductCatalogue:
        return ProductCatalogue.from_entries(
            [
                ProductCodeEntry(
                    code="ABC",
                    members=(ProductMember("AT01", "", 1), ProductMember("ST", "", 2)),
                )
            ]
        )

    def _rule(self, **fields: object) -> Rule:
        return Rule(  # type: ignore[arg-type]
            rule_id="R-1",
            source="osl",
            req_type="attributes",
            mode="include",
            applies_to="accepts",
            **fields,
        )

    def test_a_named_code_becomes_the_same_fields_present_check(self) -> None:
        (check,) = derive_checks(self._rule(product_codes=("ABC",)), self._catalogue())
        assert check.kind == "fields_present"
        assert check.values == ("AT01", "ST")
        assert check.values_from == ("ABC",)
        assert "ABC" in check.description

    def test_a_requirement_that_lists_its_attributes_is_unchanged(self) -> None:
        """The path every OSL took before product codes existed."""
        (check,) = derive_checks(self._rule(values=("AT01", "ST")))
        assert check.kind == "fields_present"
        assert check.values == ("AT01", "ST")
        assert check.values_from == ()

    def test_attributes_listed_beside_a_code_are_asked_for_once(self) -> None:
        """ "AT01 plus everything in ABC" asks for AT01 once, in the order it was said."""
        (check,) = derive_checks(
            self._rule(values=("AT01", "AGE"), product_codes=("ABC",)), self._catalogue()
        )
        assert check.values == ("AT01", "AGE", "ST")

    def test_an_undefined_code_becomes_its_own_check_and_never_an_empty_one(self) -> None:
        """The answer that matters most: "check everything in ZZZ" must not pass."""
        checks = derive_checks(self._rule(product_codes=("ABC", "ZZZ")), self._catalogue())
        kinds = {c.kind for c in checks}
        assert kinds == {"fields_present", "unknown_product_code"}
        unknown = next(c for c in checks if c.kind == "unknown_product_code")
        assert unknown.field_name == "ZZZ"

    def test_a_code_with_no_catalogue_at_all_is_reported_not_dropped(self) -> None:
        """What every caller had before the catalogue was passed in."""
        (check,) = derive_checks(self._rule(product_codes=("ABC",)))
        assert check.kind == "unknown_product_code"
        assert check.field_name == "ABC"
