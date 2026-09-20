"""Stage 4: link each requirement to the config element that implements it.

Code shortlists candidates by ``req_type`` and field alias, and links exact matches
without a call. The judge sees only the pairs code cannot settle, which is what keeps
the call volume down (``docs/design.md`` "LLM cost controls").
"""

from __future__ import annotations

import logging
from typing import Final, Sequence

from greenlight_ai.llm.prompts import TRACE_PROMPT
from greenlight_ai.llm.prompts.schemas import TraceResponse
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import guide_block, preamble
from greenlight_ai.rules.normalize import AliasTable
from greenlight_ai.rules.schema import SET_TYPES, ConfigElement, Rule, Trace

__all__ = ["run", "shortlist", "exact_match", "describe_rule"]

_LOG: Final = logging.getLogger(__name__)

#: A judge answer below this is kept but recorded as weak, so stage 8 can weigh it.
_WEAK_VERDICT: Final[float] = 0.5


def run(context: RunContext) -> None:
    """Trace every requirement to a config element.

    Args:
        context: The run context, whose ``traces`` this fills.
    """
    candidates = [e for e in context.elements if not e.is_technical and e.rule is not None]
    traces: list[Trace] = []
    by_code = 0

    for rule in context.rules:
        shortlisted = shortlist(rule, candidates, context.aliases)

        matched = next(
            (element for element in shortlisted if exact_match(rule, element, context.aliases)),
            None,
        )
        if matched is not None:
            by_code += 1
            traces.append(
                Trace(
                    rule_id=rule.rule_id,
                    element_id=matched.element_id,
                    verdict="implemented",
                    reason="Exact match on type, field, and normalized value.",
                    confidence=1.0,
                    by_code=True,
                )
            )
            continue

        if not shortlisted:
            traces.append(
                Trace(
                    rule_id=rule.rule_id,
                    verdict="not_related",
                    reason="No config element of a compatible type was found.",
                    confidence=1.0,
                    by_code=True,
                )
            )
            continue

        traces.append(_judge(context, rule, shortlisted))

    context.traces = traces
    _LOG.info(
        "run %s stage 4: %d traces (%d linked by code, %d judged)",
        context.run_id,
        len(traces),
        by_code,
        len(traces) - by_code,
    )


def shortlist(
    rule: Rule, elements: Sequence[ConfigElement], aliases: AliasTable
) -> list[ConfigElement]:
    """Narrow the candidates for one requirement, in code.

    Args:
        rule: The requirement.
        elements: Every non-technical config element.
        aliases: The attribute alias table.

    Returns:
        Elements of the same ``req_type`` that mention at least one of the same fields.
        When a rule names no fields (geography, waterfall, quantity), type alone is the
        filter, because those types have exactly one subject.
    """
    same_type = [e for e in elements if e.rule is not None and e.rule.req_type == rule.req_type]
    wanted = _fields(rule, aliases)
    if not wanted:
        return same_type
    narrowed = [e for e in same_type if wanted & _fields(e.rule, aliases)]
    # Falling back to type alone keeps a field-name mismatch from hiding the element
    # entirely: the judge can still recognise it, and a missing alias is itself worth
    # surfacing rather than silently producing "no config rule".
    return narrowed or same_type


def exact_match(rule: Rule, element: ConfigElement, aliases: AliasTable) -> bool:
    """Decide whether a pair matches exactly, so no call is needed.

    Args:
        rule: The requirement.
        element: The candidate element.
        aliases: The attribute alias table.

    Returns:
        ``True`` when type, fields, and normalized values all agree. Only then is the
        judge skipped; anything less is a question for the model.
    """
    other = element.rule
    if other is None or other.req_type != rule.req_type:
        return False

    if rule.req_type in SET_TYPES:
        return set(rule.values) == set(other.values) and rule.mode == other.mode
    if rule.req_type == "waterfall":
        return tuple(rule.steps) == tuple(other.steps)
    if rule.req_type == "quantity":
        return rule.quantity == other.quantity
    if rule.req_type == "criteria":
        return _conditions_key(rule, aliases) == _conditions_key(other, aliases)
    return False


def _conditions_key(rule: Rule, aliases: AliasTable) -> frozenset[tuple[str, str, str]]:
    """Reduce a rule's conditions to a comparable key.

    Args:
        rule: The rule.
        aliases: The attribute alias table.

    Returns:
        One ``(field, operator, value)`` triple per condition, with the field resolved
        through the alias table and the value rendered as text so ``755`` and ``755.0``
        compare equal.
    """
    return frozenset(
        (aliases.resolve(c.field_name), c.operator, _render(c.value)) for c in rule.conditions
    )


def _render(value: object) -> str:
    """Render a condition value for comparison.

    Args:
        value: The value.

    Returns:
        A stable string. Whole floats lose their trailing zero so a config's ``755.0``
        matches an OSL's ``755``.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return ",".join(_render(v) for v in value)
    return str(value)


def _fields(rule: Rule | None, aliases: AliasTable) -> frozenset[str]:
    """Collect the canonical field names a rule mentions.

    Args:
        rule: The rule, or ``None``.
        aliases: The attribute alias table.

    Returns:
        Canonical field names. Attribute requirements carry their fields in ``values``
        rather than in conditions, so both are read.
    """
    if rule is None:
        return frozenset()
    names = {c.field_name for c in rule.conditions}
    if rule.req_type == "attributes":
        names |= set(rule.values)
    return frozenset(aliases.resolve(n) for n in names if n)


def _judge(context: RunContext, rule: Rule, candidates: Sequence[ConfigElement]) -> Trace:
    """Ask the model about one requirement's candidates, best first.

    Args:
        context: The run context.
        rule: The requirement.
        candidates: The shortlisted elements.

    Returns:
        The first trace whose verdict is not ``not_related``, or a ``not_related`` trace
        when the model rejects every candidate.
    """
    best: Trace | None = None
    for element in candidates:
        result = context.client.complete(
            TRACE_PROMPT.system,
            preamble(context.guidance, "config")
            + guide_block(context.guidance)
            + TRACE_PROMPT.render(
                requirement=describe_rule(rule),
                element=_describe_element(element),
            ),
            TRACE_PROMPT.schema,
            stage="s4_trace",
            prompt_version=TRACE_PROMPT.version,
        )
        answer = result.parsed(TraceResponse)
        if answer.verdict == "not_related":
            continue
        trace = Trace(
            rule_id=rule.rule_id,
            element_id=element.element_id,
            verdict=answer.verdict,
            reason=answer.reason,
            confidence=answer.confidence,
        )
        if answer.verdict == "implemented" and answer.confidence >= _WEAK_VERDICT:
            return trace
        best = best or trace

    return best or Trace(
        rule_id=rule.rule_id,
        verdict="not_related",
        reason="No shortlisted config element implements this requirement.",
        confidence=1.0,
    )


def _describe_element(element: ConfigElement) -> str:
    """Render a config element for the judge prompt.

    The element's type and payload are always included, not just its prose description:
    a description like "the processing order" does not tell the judge which requirement
    family it belongs to, and the judge is answering a subject-matter question.

    Args:
        element: The config element.

    Returns:
        A one-line description carrying the JSON path, the canonical rule, and the
        model's own sentence. Field names and thresholds only, never a row (ADR-003).
    """
    parts = [element.json_path, describe_rule(element.rule)]
    if element.description:
        parts.append(element.description)
    return " — ".join(parts)


def describe_rule(rule: Rule | None) -> str:
    """Render a rule as one line for a prompt or a finding.

    Args:
        rule: The rule, or ``None``.

    Returns:
        A short description. Carries field names, operators, and thresholds only, never
        a sample row (ADR-003).
    """
    if rule is None:
        return "(no rule)"
    if rule.req_type in SET_TYPES:
        mode = rule.mode or "include"
        return f"{rule.req_type} — {mode} {sorted(rule.values)}"
    if rule.req_type == "waterfall":
        return f"waterfall — steps {list(rule.steps)}"
    if rule.req_type == "quantity":
        return f"quantity — {rule.quantity}"
    parts = [f"{c.field_name} {c.operator} {_render(c.value)}" for c in rule.conditions]
    joiner = f" {rule.logic} "
    return f"{rule.req_type} — {joiner.join(parts)} (action: {rule.action})"
