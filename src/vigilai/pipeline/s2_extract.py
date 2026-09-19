"""Stage 2: extract canonical requirements from the OSL, one call per section.

The model reads meaning and returns requirements; this module converts its answer into
the canonical schema and normalises the values (states to codes, numbers out of prose).
No comparison happens here (ADR-001).
"""

from __future__ import annotations

import logging
from typing import Final, cast

from vigilai.llm.prompts import EXTRACT_PROMPT
from vigilai.llm.prompts.schemas import ExtractedRequirement, ExtractResponse
from vigilai.pipeline.context import RunContext
from vigilai.pipeline.guidance import preamble
from vigilai.rules.normalize import normalize_states, parse_number
from vigilai.parsers.base import OSL_KIND
from vigilai.rules.schema import SET_TYPES, Action, AppliesTo, Condition, Rule

__all__ = ["run", "to_rule"]

_LOG: Final = logging.getLogger(__name__)

#: Sections that state no requirements. Skipping them saves a call each and keeps the
#: model from inventing a requirement out of a purpose statement.
_SKIP_HEADINGS: Final[frozenset[str]] = frozenset({"purpose", "background", "contacts"})


def run(context: RunContext) -> None:
    """Extract requirements from every OSL section.

    Args:
        context: The run context, whose ``rules`` this fills.

    Raises:
        RuntimeError: When stage 1 has not run.
    """
    if context.osl is None:
        raise RuntimeError("stage 2 requires stage 1 to have parsed the OSL")

    rules: list[Rule] = []
    for section in context.osl.sections:
        if section.heading.strip().lower() in _SKIP_HEADINGS:
            _LOG.debug("skipping OSL section %s (no requirements expected)", section.number)
            continue

        result = context.client.complete(
            EXTRACT_PROMPT.system,
            preamble(context.guidance, OSL_KIND) + EXTRACT_PROMPT.render(section=section.as_text()),
            EXTRACT_PROMPT.schema,
            stage="s2_extract",
            prompt_version=EXTRACT_PROMPT.version,
        )
        response = result.parsed(ExtractResponse)
        for extracted in response.requirements:
            rule = to_rule(extracted, rule_id=f"R-{len(rules) + 1:03d}", source_ref=section.ref)
            if rule is not None:
                rules.append(rule)

    context.rules = rules
    _LOG.info(
        "run %s stage 2: %d requirements, %d below the confidence floor",
        context.run_id,
        len(rules),
        sum(1 for r in rules if r.is_low_confidence),
    )


def to_rule(
    extracted: ExtractedRequirement, rule_id: str, source_ref: str, source: str = "osl"
) -> Rule | None:
    """Convert one model-reported requirement into the canonical schema.

    Normalisation happens here rather than in the prompt: asking the model for state
    codes instead of the words the OSL used would be asking it to transform data, and
    transformations belong in code (ADR-001).

    Args:
        extracted: What the model reported.
        rule_id: The id to assign.
        source_ref: Where it came from, shown as evidence.
        source: ``"osl"``, ``"config"``, or ``"user"``.

    Returns:
        The canonical rule, or ``None`` when the payload does not survive validation.
        A malformed requirement is dropped rather than raised: one bad section should
        not abort a run, and the gap shows up as an untraced requirement.
    """
    values: tuple[str, ...] = ()
    if extracted.req_type == "geography":
        codes, unrecognised = normalize_states(extracted.values)
        if unrecognised:
            _LOG.info(
                "rule %s: %d unrecognised state values kept verbatim", rule_id, len(unrecognised)
            )
        values = tuple(sorted(codes) + sorted(unrecognised))
    elif extracted.req_type in SET_TYPES:
        values = tuple(v.strip() for v in extracted.values if v.strip())

    conditions: list[Condition] = []
    for raw in extracted.conditions:
        value: object = raw.value
        if raw.operator not in ("is_null", "not_null") and value is not None:
            value = _as_number(value)
        try:
            conditions.append(
                Condition(
                    field_name=raw.field_name,
                    operator=raw.operator,
                    value=value,  # type: ignore[arg-type]
                )
            )
        except ValueError:
            _LOG.info("rule %s: dropped an unusable condition on %r", rule_id, raw.field_name)

    try:
        return Rule(
            rule_id=rule_id,
            source=source,  # type: ignore[arg-type]
            req_type=extracted.req_type,
            conditions=tuple(conditions),
            values=values,
            mode=extracted.mode or ("include" if extracted.req_type in SET_TYPES else None),
            steps=tuple(extracted.steps),
            quantity=extracted.quantity,
            applies_to=_as_population(extracted.applies_to),
            action=_as_action(extracted.action),
            source_ref=source_ref,
            source_text=extracted.source_text,
            confidence=extracted.confidence,
        )
    except ValueError as exc:
        _LOG.info("rule %s dropped: %s", rule_id, exc)
        return None


def _as_number(value: object) -> object:
    """Normalise a condition value to a number where possible.

    Args:
        value: The value the model reported.

    Returns:
        The number, or the original value when it is a list (``in``, ``between``) or
        cannot be read as one.
    """
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return parse_number(value)
    except ValueError:
        return value


def _as_action(value: str) -> Action:
    """Map a reported action onto the closed set.

    A model answer outside the set is coerced rather than rejected: the requirement is
    still real, and the default is the safe reading.

    Args:
        value: What the model said.

    Returns:
        A valid action, defaulting to ``"accept"``.
    """
    lowered = value.strip().lower()
    if lowered in ("accept", "reject", "tag", "pass"):
        return cast(Action, lowered)
    return "accept"


def _as_population(value: str) -> AppliesTo:
    """Map a reported population onto the closed set.

    Args:
        value: What the model said.

    Returns:
        A valid population, defaulting to ``"all"``.
    """
    lowered = value.strip().lower()
    if lowered in ("all", "accepts", "rejects"):
        return cast(AppliesTo, lowered)
    return "all"
