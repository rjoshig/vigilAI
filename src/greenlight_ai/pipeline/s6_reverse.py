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


def _check_compliance(context: RunContext, admin: AdminConfig, customer: str) -> None:
    """Assert every in-scope compliance rule is present in the config.

    Args:
        context: The run context.
        admin: The admin configuration.
        customer: The run's customer.
    """
    if context.config is None:
        return

    paths = [block.json_path for block in context.config.blocks]
    for rule in admin.compliance_rules:
        if not rule.applies_to(customer):
            continue
        matching = [p for p in paths if rule.json_path_contains in p]
        if matching:
            continue
        context.add_finding(
            Finding(
                finding_id=context.next_finding_id(),
                type="rule_missing_in_config",
                severity="high",
                title=f"Compliance rule {rule.name!r} is not implemented in the config",
                detail=(
                    f"{rule.reasoning or 'This rule must be present in every config in scope.'} "
                    f"No config path contains {rule.json_path_contains!r}."
                ),
                leg="osl_config",
                evidence=Evidence(config_path=rule.json_path_contains),
            )
        )
