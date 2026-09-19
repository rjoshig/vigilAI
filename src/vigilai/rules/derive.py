"""Derived report checks: what each rule implies the reports must show.

Every rule also produces the report expectations it implies. ``age < 21 -> reject``
generates ``accepts.age.min >= 21``. These derivations are fixed code per operator,
never LLM output (``docs/design.md`` "Canonical rule schema"; ADR-001), so the same
requirement always yields the same expectation and a report check can never be
hallucinated into existence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Sequence

from vigilai.rules.normalize import Interval, interval_from_condition
from vigilai.rules.schema import Rule

__all__ = ["CheckKind", "DerivedCheck", "derive_checks", "INVERSE_OPERATOR"]

#: What a derived check asserts about a report.
CheckKind = Literal[
    "min_at_least",
    "min_greater_than",
    "max_at_most",
    "max_less_than",
    "value_set_subset",
    "value_set_superset",
    "value_set_excludes",
    "fields_present",
    "step_order",
    "count_equals",
    "counts_reconcile",
]

#: Turning a rejection rule into an acceptance expectation flips the operator. Stated as
#: data so the flip is auditable and cannot drift between call sites.
INVERSE_OPERATOR: Final[dict[str, str]] = {
    "<": ">=",
    "<=": ">",
    ">": "<=",
    ">=": "<",
    "=": "!=",
    "!=": "=",
    "in": "not_in",
    "not_in": "in",
}


@dataclass(frozen=True, slots=True)
class DerivedCheck:
    """One expectation a rule places on the reports.

    Attributes:
        kind: What is asserted.
        population: Which population the expectation applies to, e.g. ``"accepts"``.
        field_name: The attribute involved, empty for whole-report checks.
        value: The number the check compares against, when it has one.
        values: The set the check compares against, when it has one.
        steps: The expected step order, for ``step_order``.
        rule_id: The rule this came from, so a failure names its requirement.
        description: The check in words, shown as the reason on a finding.
    """

    kind: CheckKind
    population: str
    field_name: str = ""
    value: float | None = None
    values: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    rule_id: str = ""
    description: str = ""


def derive_checks(rule: Rule) -> tuple[DerivedCheck, ...]:
    """Derive every report expectation implied by a rule.

    Args:
        rule: The canonical rule, from the OSL or from the config.

    Returns:
        The checks, empty when the rule implies nothing checkable in a report (a free-text
        ``other`` requirement, for instance, which is marked for manual verification).
    """
    if rule.req_type == "criteria":
        return _criteria_checks(rule)
    if rule.req_type == "geography":
        return _set_checks(rule, field_name="state")
    if rule.req_type == "value_set":
        field_name = rule.conditions[0].field_name if rule.conditions else ""
        return _set_checks(rule, field_name=field_name)
    if rule.req_type == "attributes":
        return (
            DerivedCheck(
                kind="fields_present",
                population=_population(rule),
                values=rule.values,
                rule_id=rule.rule_id,
                description=f"{len(rule.values)} requested attributes must be present",
            ),
        )
    if rule.req_type == "waterfall":
        return (
            DerivedCheck(
                kind="step_order",
                population="all",
                steps=rule.steps,
                rule_id=rule.rule_id,
                description="waterfall steps must appear in this order: " + " → ".join(rule.steps),
            ),
            DerivedCheck(
                kind="counts_reconcile",
                population="all",
                rule_id=rule.rule_id,
                description="accepts + rejects must equal the input count",
            ),
        )
    if rule.req_type == "quantity" and rule.quantity is not None:
        return (
            DerivedCheck(
                kind="count_equals",
                population=_population(rule),
                value=rule.quantity,
                rule_id=rule.rule_id,
                description=f"delivered count must equal {rule.quantity:g}",
            ),
        )
    return ()


def _population(rule: Rule) -> str:
    """Decide which population a rule's expectation applies to.

    A rule that rejects on a condition constrains what survives, so its expectation is
    about accepts even though the rule itself talks about rejects.

    Args:
        rule: The rule.

    Returns:
        The population name used by the report checks.
    """
    if rule.applies_to != "all":
        return rule.applies_to
    return "accepts" if rule.action in ("accept", "reject") else "all"


def _criteria_checks(rule: Rule) -> tuple[DerivedCheck, ...]:
    """Derive min/max expectations from numeric conditions.

    An OR of conditions constrains nothing on its own: a record may satisfy either
    branch, so neither branch bounds the delivered population. Such a rule yields no
    derived check rather than a wrong one.

    Args:
        rule: A ``criteria`` rule.

    Returns:
        One check per condition, or none when the conditions are OR-joined.
    """
    if rule.logic == "OR" and len(rule.conditions) > 1:
        return ()

    checks: list[DerivedCheck] = []
    population = _population(rule)
    for condition in rule.conditions:
        # A rejection rule states what is thrown away, so the report expectation is the
        # inverse: "reject age < 21" means the accepts file must start at 21.
        operator: str = condition.operator
        if rule.action == "reject":
            inverted = INVERSE_OPERATOR.get(operator)
            if inverted is None:
                continue
            operator = inverted
        interval = _interval_or_none(operator, condition.value)
        if interval is None:
            continue
        checks.extend(_checks_from_interval(interval, condition.field_name, population, rule))
    return tuple(checks)


def _interval_or_none(operator: str, value: object) -> Interval | None:
    """Build an interval, treating an unreadable value as "no expectation".

    A condition whose value cannot be parsed is an extraction problem, and it is already
    visible as a low-confidence rule; inventing a check from it would produce a
    misleading finding.

    Args:
        operator: The comparison operator.
        value: The comparison value.

    Returns:
        The interval, or ``None``.
    """
    try:
        return interval_from_condition(operator, value)
    except ValueError:
        return None


def _checks_from_interval(
    interval: Interval, field_name: str, population: str, rule: Rule
) -> Sequence[DerivedCheck]:
    """Turn an interval into the min/max checks it implies.

    Args:
        interval: The accepted range.
        field_name: The attribute.
        population: Which population to check.
        rule: The originating rule, for provenance.

    Returns:
        Up to two checks, one per bound.
    """
    checks: list[DerivedCheck] = []
    if interval.lower is not None:
        kind: CheckKind = "min_at_least" if interval.lower_inclusive else "min_greater_than"
        symbol = ">=" if interval.lower_inclusive else ">"
        checks.append(
            DerivedCheck(
                kind=kind,
                population=population,
                field_name=field_name,
                value=interval.lower,
                rule_id=rule.rule_id,
                description=f"{population}.{field_name}.min {symbol} {interval.lower:g}",
            )
        )
    if interval.upper is not None:
        kind = "max_at_most" if interval.upper_inclusive else "max_less_than"
        symbol = "<=" if interval.upper_inclusive else "<"
        checks.append(
            DerivedCheck(
                kind=kind,
                population=population,
                field_name=field_name,
                value=interval.upper,
                rule_id=rule.rule_id,
                description=f"{population}.{field_name}.max {symbol} {interval.upper:g}",
            )
        )
    return checks


def _set_checks(rule: Rule, field_name: str) -> tuple[DerivedCheck, ...]:
    """Derive the expectation a set requirement places on a distribution report.

    Args:
        rule: A ``geography`` or ``value_set`` rule.
        field_name: The attribute the set constrains.

    Returns:
        A single check: an include-list means the report's keys must be a subset of it;
        an exclude-list means none of its members may appear.
    """
    population = _population(rule)
    if rule.mode == "exclude":
        return (
            DerivedCheck(
                kind="value_set_excludes",
                population=population,
                field_name=field_name,
                values=rule.values,
                rule_id=rule.rule_id,
                description=f"no {field_name} may be one of {sorted(rule.values)}",
            ),
        )
    return (
        DerivedCheck(
            kind="value_set_subset",
            population=population,
            field_name=field_name,
            values=rule.values,
            rule_id=rule.rule_id,
            description=f"every {field_name} must be one of {sorted(rule.values)}",
        ),
    )
