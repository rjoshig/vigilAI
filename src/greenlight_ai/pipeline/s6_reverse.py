"""Stage 6: the scoped reverse pass. Pure code, no LLM call.

The reverse pass is scoped, not exhaustive, because the OSL does not describe every
detail of the extract process (``docs/design.md`` "Processing pipeline", step 6). Only
three categories of config element are checked back against the OSL: filters and select
criteria, model data such as attributes, and fixed compliance rules. Compliance rules
work the other way round: each one must be present in the config even if the OSL never
mentions it.
"""

from __future__ import annotations

import logging
from typing import Final

from greenlight_ai.checks.definitions import AdminConfig
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.s4_trace import describe_rule
from greenlight_ai.rules.schema import Evidence, Finding

__all__ = ["run"]

_LOG: Final = logging.getLogger(__name__)


def run(context: RunContext) -> None:
    """Check scoped config elements back against the OSL, and compliance both ways.

    Args:
        context: The run context, whose ``findings`` this appends to. Its ``admin``
            field supplies the categories and compliance rules, and ``customer`` scopes
            them.
    """
    settings = context.admin
    customer = context.customer
    checked_kinds = {
        kind for category in settings.categories if category.checked for kind in category.kinds
    }
    traced_element_ids = {t.element_id for t in context.traces if t.element_id is not None}
    before = len(context.findings)

    for element in context.elements:
        if element.is_technical or element.rule is None:
            continue
        if element.element_id in traced_element_ids:
            continue
        kind = element.json_path.split(".")[0].split("[")[0]
        if kind not in checked_kinds:
            _LOG.debug("reverse pass skips %s (category not checked)", element.json_path)
            continue

        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="extra_rule_in_config",
                severity="medium",
                title=f"Config element {element.json_path} has no matching OSL requirement",
                detail=(
                    f"The config applies {describe_rule(element.rule)}, and no OSL "
                    "requirement calls for it. Category is in the reverse-pass scope."
                ),
                leg="osl_config",
                element_id=element.element_id,
                evidence=Evidence(
                    config_path=element.json_path,
                    config_value=describe_rule(element.rule),
                ),
            )
        )

    _check_compliance(context, settings, customer)

    _LOG.info(
        "run %s stage 6: %d findings from the reverse pass",
        context.run_id,
        len(context.findings) - before,
    )


#: What a finding says when the rule's author gave no reasoning.
_PRESENCE_REASON: Final[str] = "This rule must be present in every config in scope."


def _check_compliance(context: RunContext, admin: AdminConfig, customer: str) -> None:
    """Assert every in-scope compliance rule is present in the config.

    Args:
        context: The run context.
        admin: The admin configuration.
        customer: The run's customer.
    """
    if context.config is None:
        return

    for rule in admin.compliance_rules:
        if not rule.applies_to(customer, context.guidance.scope_code):
            continue
        ref = f"compliance_rule:{rule.id}" if rule.id is not None else ""
        shadow = bool(ref) and ref in admin.shadow_rule_refs
        matching = [b for b in context.config.blocks if rule.json_path_contains in b.json_path]
        if not matching:
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="rule_missing_in_config",
                    severity="high",
                    title=f"Compliance rule {rule.name!r} is not implemented in the config",
                    detail=(
                        f"{rule.reasoning or _PRESENCE_REASON} "
                        f"No config path contains {rule.json_path_contains!r}."
                    ),
                    leg="osl_config",
                    rule_ref=ref,
                    shadow=shadow,
                    evidence=Evidence(config_path=rule.json_path_contains),
                )
            )
            continue

        # Presence was the whole check until 6.13a; a flag explicitly set to false passed.
        # A scalar at the path is compared with the expected value in code. A block that
        # holds a structure is presence-only, because "true" against an object means
        # nothing, and saying so beats guessing.
        mismatched = [
            b
            for b in matching
            if _is_scalar(b.content) and not _same_value(b.content, rule.expected_value)
        ]
        if mismatched and len(mismatched) == sum(1 for b in matching if _is_scalar(b.content)):
            block = mismatched[0]
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="value_mismatch",
                    severity="high",
                    title=f"Compliance rule {rule.name!r} is set to a different value",
                    detail=(
                        f"{rule.reasoning or _PRESENCE_REASON} "
                        f"{block.json_path} is {block.content!r}; the rule expects "
                        f"{rule.expected_value!r}."
                    ),
                    leg="osl_config",
                    rule_ref=ref,
                    shadow=shadow,
                    evidence=Evidence(config_path=block.json_path, config_value=str(block.content)),
                )
            )


def _is_scalar(value: object) -> bool:
    """Whether a config value can be compared with an expected value at all."""
    return isinstance(value, (bool, int, float, str)) and not isinstance(value, bytes)


def _same_value(actual: object, expected: object) -> bool:
    """Compare a scalar config value with the value a compliance rule expects.

    Args:
        actual: What the configuration holds at the path.
        expected: What the rule says it must be.

    Returns:
        ``True`` when they agree, reading ``"true"``/``"yes"`` as booleans and numbers
        as numbers, because a configuration writes ``true`` where a rule's author typed
        ``True`` and neither of them is wrong.
    """
    if expected is None:
        return True
    left, right = str(actual).strip().lower(), str(expected).strip().lower()
    truthy, falsy = {"true", "yes", "1", "on"}, {"false", "no", "0", "off"}
    if left in truthy | falsy and right in truthy | falsy:
        return (left in truthy) == (right in truthy)
    try:
        return float(left) == float(right)
    except ValueError:
        return left == right
