"""Stage 6: the scoped reverse pass. Code decides; the model is asked one question.

The reverse pass is scoped, not exhaustive, because the OSL does not describe every
detail of the extract process (``docs/design.md`` "Processing pipeline", step 6). Only
three categories of config element are checked back against the OSL: filters and select
criteria, model data such as attributes, and fixed compliance rules. Compliance rules
work the other way round: each one must be present in the config even if the OSL never
mentions it.

**This stage made no model call until Phase 6.15.** It now makes one, and only in one
place: when the deterministic matcher has failed to find a compliance control, the
model is asked *where the control is, if anywhere* — never whether the delivery is
compliant. Code checks the answer against the paths it offered, applies a confidence
floor, and turns a located control into a **review-severity** finding for a person to
confirm, never into a pass. The high-severity miss is unchanged when the answer is
"absent", which it usually is.

Why the call is worth its cost: a substring match could not distinguish a control that
is *absent* from one that is *spelled differently*, and reported both at high severity.
Option C narrowed that deterministically; this closes what is left. The call happens on
the exception rather than on every run, and not at all when the match succeeds.
"""

from __future__ import annotations

import logging
from typing import Final

from greenlight_ai.checks import compliance_match
from greenlight_ai.checks.definitions import AdminConfig, ComplianceRule
from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.prompts import COMPLIANCE_LOCATE_PROMPT
from greenlight_ai.llm.prompts.schemas import ComplianceLocation
from greenlight_ai.pipeline.guidance import preamble
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


#: Below this the model's own answer is treated as "unsure": a locator that is not
#: confident has told us nothing the deterministic match had not already.
_LOCATE_CONFIDENCE_FLOOR: Final[float] = 0.6

#: How many configuration paths the model is shown. A configuration is not a search
#: space, and a prompt that is mostly paths stops being a prompt.
_LOCATE_MAX_PATHS: Final[int] = 120


def _may_locate(context: RunContext) -> bool:
    """Whether this run may spend a model call locating a compliance control.

    Args:
        context: The run context.

    Returns:
        True when a client is available and the run has budget. A run that has
        exhausted its budget falls back to the deterministic answer rather than
        failing, because the deterministic answer is what it would have had anyway.
    """
    return context.client is not None


def _locate(context: RunContext, rule: ComplianceRule) -> ComplianceLocation | None:
    """Ask where a configuration implements a control, if anywhere.

    The model is shown paths and the shape of their contents — never a value, which is
    ADR-003 — and answers one narrow question. It does not decide compliance; the
    caller turns the answer into a severity, which is ADR-001.

    Args:
        context: The run context.
        rule: The compliance rule whose control could not be found.

    Returns:
        The model's answer, or ``None`` when it could not be obtained or cannot be
        believed — an unparseable reply, a path that was not in the list, or an answer
        the model itself was not confident in.
    """
    if context.config is None:
        return None
    paths = [b.json_path for b in context.config.blocks][:_LOCATE_MAX_PATHS]
    if not paths:
        return None

    shapes = {b.json_path: type(b.content).__name__ for b in context.config.blocks}
    listed = "\n".join(f"- {path} ({shapes.get(path, 'value')})" for path in paths)
    control = f"{rule.name} — {rule.reasoning or _PRESENCE_REASON}"

    try:
        result = context.client.complete(
            COMPLIANCE_LOCATE_PROMPT.system,
            preamble(context.guidance)
            + COMPLIANCE_LOCATE_PROMPT.render_with_examples(
                context.examples.get("compliance_locate", ()),
                control=control,
                paths=listed,
            ),
            ComplianceLocation,
            stage="compliance_locate",
            prompt_version=COMPLIANCE_LOCATE_PROMPT.version,
        )
        answer = result.parsed(ComplianceLocation)
    except LLMError as exc:
        _LOG.info("compliance %r: locator did not answer (%s)", rule.name, type(exc).__name__)
        return None

    if answer.verdict != "found":
        return None
    # The model was told to quote a path from the list. Code checks that it did:
    # a path nobody offered is a hallucination, and believing one would be the
    # comparison ADR-001 keeps out of the model's hands.
    if answer.json_path not in set(paths):
        _LOG.info(
            "compliance %r: locator proposed %r, which is not a path in this "
            "configuration; ignored",
            rule.name,
            answer.json_path,
        )
        return None
    if answer.confidence < _LOCATE_CONFIDENCE_FLOOR:
        _LOG.info(
            "compliance %r: locator proposed %r at confidence %.2f; below the floor",
            rule.name,
            answer.json_path,
            answer.confidence,
        )
        return None
    return answer


def _report_located(
    context: RunContext,
    rule: ComplianceRule,
    located: ComplianceLocation,
    ref: str,
    shadow: bool,
) -> None:
    """Report a control found somewhere the rule does not name.

    Deliberately **not** a pass and deliberately **not** a high-severity miss. The
    model located something; a person decides whether it is the control, and
    confirming it adds the path to the rule so the next run matches in code.

    Args:
        context: The run context, whose ``findings`` this appends to.
        rule: The rule whose control was located.
        located: The model's answer, already checked against the offered paths.
        ref: The rule reference for statistics.
        shadow: Whether the rule is running in shadow.
    """
    context.add_finding(
        Finding(
            finding_id=context.next_finding_id(),
            type="could_not_evaluate",
            severity="review",
            title=(
                f"Compliance rule {rule.name!r} may be implemented at "
                f"{located.json_path}, which the rule does not name"
            ),
            detail=(
                f"{rule.reasoning or _PRESENCE_REASON} No configuration path matched "
                f"{rule.json_path_contains!r}, so the configuration was read for the "
                f"control itself: {located.reason} "
                "Confirm whether this is the control. If it is, add the path to the "
                "rule as an alternate and the next run will match it in code, without "
                "asking again."
            ),
            leg="osl_config",
            rule_ref=ref,
            shadow=shadow,
            engine="model",
            confidence=located.confidence,
            evidence=Evidence(config_path=located.json_path),
        )
    )
    _LOG.info(
        "compliance %r located at %r (confidence %.2f)",
        rule.name,
        located.json_path,
        located.confidence,
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

    for rule in admin.compliance_rules:
        if not rule.applies_to(customer, context.guidance.scope_code):
            continue
        ref = f"compliance_rule:{rule.id}" if rule.id is not None else ""
        shadow = bool(ref) and ref in admin.shadow_rule_refs
        # Widened in 6.15: a substring test on the path could not tell a control
        # that is absent from one that is spelled differently or nested a level
        # deeper, and reported both at high severity.
        hits = compliance_match.matches(
            rule.json_path_contains,
            [(b.json_path, b.content) for b in context.config.blocks],
            rule.alternates,
        )
        found = {hit.json_path for hit in hits}
        matching = [b for b in context.config.blocks if b.json_path in found]
        if not matching and _may_locate(context):
            # Four code tests have already failed, so the honest prior is that the
            # control is absent. Ask once where it is anyway, because "absent" and
            # "implemented under a name this rule does not know" are the two things
            # the deterministic match cannot tell apart, and one of them is a false
            # high-severity finding (Phase 6.15, option A).
            located = _locate(context, rule)
            if located is not None:
                _report_located(context, rule, located, ref, shadow)
                continue
        if not matching:
            context.add_finding(
                Finding(
                    finding_id=context.next_finding_id(),
                    type="rule_missing_in_config",
                    severity="high",
                    title=f"Compliance rule {rule.name!r} is not implemented in the config",
                    detail=(
                        f"{rule.reasoning or _PRESENCE_REASON} "
                        f"No configuration path implements {rule.json_path_contains!r}"
                        + (
                            f", nor any of {list(rule.alternates)}."
                            if rule.alternates
                            else ". Spelling and nesting were allowed for; if this "
                            "customer calls it something else, add that path to the "
                            "rule as an alternate."
                        )
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
