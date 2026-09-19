"""Stage 5: compare a requirement with the element that implements it, in code.

Every comparison in the product happens here or in :mod:`greenlight_ai.checks`: sets,
intervals with their operators, attribute lists, waterfall order, and quantities. The
model is never asked whether two values agree (ADR-001).
"""

from __future__ import annotations

import logging
from typing import Final

from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.s4_trace import describe_rule
from greenlight_ai.rules.normalize import Interval, interval_from_condition
from greenlight_ai.rules.schema import SET_TYPES, Condition, ConfigElement, Evidence, Finding, Rule

__all__ = ["run"]

_LOG: Final = logging.getLogger(__name__)

#: A requirement the config does not implement is the most serious kind of gap: the
#: delivery cannot satisfy the OSL by accident.
_MISSING_SEVERITY: Final[str] = "high"


def run(context: RunContext) -> None:
    """Compare every traced pair and record what differs.

    Args:
        context: The run context, whose ``findings`` this appends to.
    """
    before = len(context.findings)

    for rule in context.rules:
        if rule.is_low_confidence:
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="low_confidence_extraction",
                    severity="review",
                    title=f"Requirement {rule.rule_id} was extracted with low confidence",
                    detail=(
                        f"Confidence {rule.confidence:.2f} is below the 0.70 floor. "
                        f"Read as: {describe_rule(rule)}"
                    ),
                    leg="osl_config",
                    rule_id=rule.rule_id,
                    evidence=Evidence(osl_ref=rule.source_ref, osl_text=rule.source_text),
                )
            )

        trace = context.trace_for(rule.rule_id)
        if trace is None or trace.element_id is None or trace.verdict == "not_related":
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="rule_missing_in_config",
                    severity=_MISSING_SEVERITY,  # type: ignore[arg-type]
                    title=f"No config rule implements requirement {rule.rule_id}",
                    detail=(
                        f"The OSL requires: {describe_rule(rule)}. "
                        f"{trace.reason if trace else 'No trace was produced.'}"
                    ),
                    leg="osl_config",
                    rule_id=rule.rule_id,
                    evidence=Evidence(osl_ref=rule.source_ref, osl_text=rule.source_text),
                )
            )
            continue

        element = context.element(trace.element_id)
        if element is None or element.rule is None:
            continue
        _compare(context, rule, element, element.rule)

    _LOG.info(
        "run %s stage 5: %d findings from value comparison",
        context.run_id,
        len(context.findings) - before,
    )


def _compare(context: RunContext, rule: Rule, element: ConfigElement, other: Rule) -> None:
    """Dispatch to the comparison for this requirement type.

    Args:
        context: The run context.
        rule: The OSL requirement.
        element: The config element.
        other: The element's rule.
    """
    if rule.req_type in SET_TYPES:
        _compare_sets(context, rule, element, other)
    elif rule.req_type == "criteria":
        _compare_criteria(context, rule, element, other)
    elif rule.req_type == "waterfall":
        _compare_steps(context, rule, element, other)
    elif rule.req_type == "quantity":
        _compare_quantity(context, rule, element, other)


def _evidence(rule: Rule, element: ConfigElement, other: Rule) -> Evidence:
    """Build the OSL-and-config half of a finding's evidence.

    Args:
        rule: The OSL requirement.
        element: The config element.
        other: The element's rule.

    Returns:
        Evidence carrying the OSL location and text and the config path and value.
    """
    return Evidence(
        osl_ref=rule.source_ref,
        osl_text=rule.source_text,
        config_path=element.json_path,
        config_value=describe_rule(other),
    )


def _compare_sets(context: RunContext, rule: Rule, element: ConfigElement, other: Rule) -> None:
    """Compare two sets, reporting the exact members that differ.

    Args:
        context: The run context.
        rule: The OSL requirement.
        element: The config element.
        other: The element's rule.
    """
    required = set(rule.values)
    configured = set(other.values)
    missing = sorted(required - configured)
    extra = sorted(configured - required)

    if rule.mode != other.mode and other.mode is not None:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="operator_mismatch",
                severity="high",
                title=f"{rule.req_type} mode differs for {rule.rule_id}",
                detail=(
                    f"The OSL states an {rule.mode} list; the config applies an "
                    f"{other.mode} list. The same values then mean the opposite thing."
                ),
                leg="osl_config",
                rule_id=rule.rule_id,
                element_id=element.element_id,
                evidence=_evidence(rule, element, other),
            )
        )
        return

    if missing:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="rule_missing_in_config",
                severity="high",
                title=f"Config omits {len(missing)} value(s) the OSL requires",
                detail=f"Missing from the config: {', '.join(missing)}.",
                leg="osl_config",
                rule_id=rule.rule_id,
                element_id=element.element_id,
                evidence=_evidence(rule, element, other),
            )
        )
    if extra:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="extra_rule_in_config",
                severity="medium",
                title=f"Config includes {len(extra)} value(s) the OSL does not allow",
                detail=f"In the config but not the OSL: {', '.join(extra)}.",
                leg="osl_config",
                rule_id=rule.rule_id,
                element_id=element.element_id,
                evidence=_evidence(rule, element, other),
            )
        )


def _compare_criteria(context: RunContext, rule: Rule, element: ConfigElement, other: Rule) -> None:
    """Compare numeric conditions field by field.

    A value difference and an operator difference are separate finding types, so the
    interval's bounds and its inclusivity are compared separately.

    Args:
        context: The run context.
        rule: The OSL requirement.
        element: The config element.
        other: The element's rule.
    """
    aliases = context.aliases
    by_field: dict[str, Condition] = {aliases.resolve(c.field_name): c for c in other.conditions}

    # Stage 4 already decided this element implements this requirement. When each side
    # states exactly one condition and the alias table has never heard of the OSL's
    # attribute, the two are about the same thing: the config calls it something the
    # table does not map yet. Pairing them beats reporting a phantom "no condition on
    # score", which is what an unseeded alias table produced on every run.
    #
    # The guard is deliberately narrow. If the table *does* know the attribute, a
    # missing counterpart is a real gap: "score" against a config that only constrains
    # "age" is a missing rule, not a naming difference.
    single = len(rule.conditions) == 1 and len(other.conditions) == 1

    for condition in rule.conditions:
        field_name = aliases.resolve(condition.field_name)
        counterpart = by_field.get(field_name)
        if counterpart is None and single and not aliases.knows(condition.field_name):
            counterpart = other.conditions[0]
            _LOG.info(
                "run %s: pairing %r with %r by position; no alias links them",
                context.run_id,
                condition.field_name,
                counterpart.field_name,
            )
        if counterpart is None:
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="rule_missing_in_config",
                    severity="high",
                    title=f"Config has no condition on {condition.field_name}",
                    detail=(
                        f"The OSL constrains {condition.field_name} "
                        f"({condition.operator} {condition.value}); the linked config "
                        f"element constrains {sorted(by_field) or 'nothing'}."
                    ),
                    leg="osl_config",
                    rule_id=rule.rule_id,
                    element_id=element.element_id,
                    evidence=_evidence(rule, element, other),
                )
            )
            continue

        wanted = _interval(condition)
        got = _interval(counterpart)
        if wanted is None or got is None:
            if condition.operator != counterpart.operator:
                _operator_finding(context, rule, element, other, condition, counterpart)
            continue

        if not wanted.same_bounds_as(got):
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="value_mismatch",
                    severity="high",
                    title=(
                        f"{condition.field_name}: OSL says {_bound(wanted)}, "
                        f"config says {_bound(got)}"
                    ),
                    detail=(
                        f"The OSL requires {condition.field_name} {condition.operator} "
                        f"{condition.value}; the config applies {counterpart.operator} "
                        f"{counterpart.value}."
                    ),
                    leg="osl_config",
                    rule_id=rule.rule_id,
                    element_id=element.element_id,
                    evidence=_evidence(rule, element, other),
                )
            )
        elif (
            wanted.lower_inclusive != got.lower_inclusive
            or wanted.upper_inclusive != got.upper_inclusive
        ):
            _operator_finding(context, rule, element, other, condition, counterpart)


def _operator_finding(
    context: RunContext,
    rule: Rule,
    element: ConfigElement,
    other: Rule,
    condition: Condition,
    counterpart: Condition,
) -> None:
    """Record a boundary-operator difference.

    Args:
        context: The run context.
        rule: The OSL requirement.
        element: The config element.
        other: The element's rule.
        condition: The OSL condition.
        counterpart: The config condition.
    """
    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="operator_mismatch",
            severity="high",
            title=(
                f"{condition.field_name}: OSL uses {condition.operator}, "
                f"config uses {counterpart.operator}"
            ),
            detail=(
                "The thresholds agree but the boundary does not, so records exactly at "
                f"{condition.value} are treated differently."
            ),
            leg="osl_config",
            rule_id=rule.rule_id,
            element_id=element.element_id,
            evidence=_evidence(rule, element, other),
        )
    )


def _compare_steps(context: RunContext, rule: Rule, element: ConfigElement, other: Rule) -> None:
    """Compare waterfall step order.

    Args:
        context: The run context.
        rule: The OSL requirement.
        element: The config element.
        other: The element's rule.
    """
    wanted = [s.strip().lower() for s in rule.steps]
    got = [s.strip().lower() for s in other.steps]

    # A config's step list carries boundary markers the OSL never mentions, such as the
    # input step, and may add steps of its own. Extra config steps are the reverse
    # pass's business (stage 6), so order is judged on the steps the two share and a
    # step the OSL requires but the config lacks is reported as missing.
    missing = [s for s in wanted if s not in got]
    shared_wanted = [s for s in wanted if s in got]
    shared_got = [s for s in got if s in wanted]

    if missing:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="rule_missing_in_config",
                severity="high",
                title=f"Config omits {len(missing)} waterfall step(s) the OSL requires",
                detail=(
                    f"Missing from the config pipeline: {', '.join(missing)}. "
                    f"OSL order: {' → '.join(rule.steps)}."
                ),
                leg="osl_config",
                rule_id=rule.rule_id,
                element_id=element.element_id,
                evidence=_evidence(rule, element, other),
            )
        )

    if shared_wanted != shared_got:
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="waterfall_order_mismatch",
                severity="high",
                title="Waterfall steps run in a different order than the OSL states",
                detail=(
                    f"OSL order: {' → '.join(shared_wanted)}. "
                    f"Config order: {' → '.join(shared_got)}."
                ),
                leg="osl_config",
                rule_id=rule.rule_id,
                element_id=element.element_id,
                evidence=_evidence(rule, element, other),
            )
        )


def _compare_quantity(context: RunContext, rule: Rule, element: ConfigElement, other: Rule) -> None:
    """Compare a delivered-quantity requirement.

    Args:
        context: The run context.
        rule: The OSL requirement.
        element: The config element.
        other: The element's rule.
    """
    if rule.quantity == other.quantity:
        return
    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="value_mismatch",
            severity="high",
            title=f"Quantity differs: OSL says {rule.quantity}, config says {other.quantity}",
            detail="The delivered record count the config targets is not the one the OSL states.",
            leg="osl_config",
            rule_id=rule.rule_id,
            element_id=element.element_id,
            evidence=_evidence(rule, element, other),
        )
    )


def _interval(condition: Condition) -> Interval | None:
    """Build the interval a condition accepts, or ``None``.

    Args:
        condition: The condition.

    Returns:
        The interval, or ``None`` when the operator has none or the value is unreadable.
    """
    try:
        return interval_from_condition(condition.operator, condition.value)
    except ValueError:
        return None


def _bound(interval: Interval) -> str:
    """Render an interval for a finding title.

    Args:
        interval: The interval.

    Returns:
        Its standard notation.
    """
    return str(interval)
