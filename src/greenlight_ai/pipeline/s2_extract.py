"""Stage 2: extract canonical requirements from the OSL, one call per section.

The model reads meaning and returns requirements; this module converts its answer into
the canonical schema and normalises the values (states to codes, numbers out of prose).
No comparison happens here (ADR-001).
"""

from __future__ import annotations

import logging
from typing import Any, Final, cast

from greenlight_ai.llm.prompts import EXTRACT_PROMPT
from greenlight_ai.llm.prompts.schemas import ExtractedRequirement, ExtractResponse
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import preamble
from greenlight_ai.rules.normalize import normalize_states, parse_number
from greenlight_ai.parsers.base import OSL_KIND
from greenlight_ai.rules.schema import SET_TYPES, Action, AppliesTo, Condition, Rule

__all__ = ["normalize_elements", "normalize_response", "run", "to_rule"]

_LOG: Final = logging.getLogger(__name__)

#: Sections that state no requirements. Skipping them saves a call each and keeps the
#: model from inventing a requirement out of a purpose statement.
_SKIP_HEADINGS: Final[frozenset[str]] = frozenset({"purpose", "background", "contacts"})

#: Keys the schema accepts on a requirement. Anything else a model adds is dropped.
_REQUIREMENT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "req_type",
        "conditions",
        "values",
        "mode",
        "steps",
        "quantity",
        "action",
        "applies_to",
        "source_text",
        "confidence",
    }
)

#: Keys the schema accepts on a condition.
_CONDITION_KEYS: Final[frozenset[str]] = frozenset({"field_name", "operator", "value"})

#: Synonyms a real model uses for ``values``; the first one present wins.
_VALUE_SYNONYMS: Final[tuple[str, ...]] = ("values", "fields", "attributes", "items", "states")

#: Synonyms for a condition's ``field_name``.
_FIELD_SYNONYMS: Final[tuple[str, ...]] = ("field_name", "field", "attribute", "name")

#: Requirement types a model invents, folded onto the closed set.
_REQ_TYPE_ALIASES: Final[dict[str, str]] = {
    "criterion": "criteria",
    "threshold": "criteria",
    "numeric": "criteria",
    "state": "geography",
    "states": "geography",
    "region": "geography",
    "exclusion": "value_set",
    "exclusions": "value_set",
    "inclusion": "value_set",
    "value_list": "value_set",
    "values": "value_set",
    "attribute": "attributes",
    "fields": "attributes",
    "output": "attributes",
    "order": "waterfall",
    "sequence": "waterfall",
    "processing_order": "waterfall",
    "count": "quantity",
    "volume": "quantity",
}

#: Operators a model spells differently, folded onto the closed set.
_OPERATOR_ALIASES: Final[dict[str, str]] = {
    "==": "=",
    "eq": "=",
    "equals": "=",
    "equal": "=",
    "<>": "!=",
    "ne": "!=",
    "not_equal": "!=",
    "gt": ">",
    "gte": ">=",
    "ge": ">=",
    "lt": "<",
    "lte": "<=",
    "le": "<=",
    "at_least": ">=",
    "at_most": "<=",
    "not in": "not_in",
    "notin": "not_in",
    "is null": "is_null",
    "null": "is_null",
    "not null": "not_null",
    "is_not_null": "not_null",
}

_VALID_REQ_TYPES: Final[frozenset[str]] = frozenset(
    {"criteria", "geography", "value_set", "attributes", "waterfall", "quantity", "other"}
)
_VALID_OPERATORS: Final[frozenset[str]] = frozenset(
    {"<", "<=", ">", ">=", "=", "!=", "in", "not_in", "between", "is_null", "not_null"}
)


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
            preamble(context.guidance, OSL_KIND)
            + EXTRACT_PROMPT.render_with_examples(
                context.examples.get("s2_extract", ()), section=section.as_text()
            ),
            EXTRACT_PROMPT.schema,
            stage="s2_extract",
            prompt_version=EXTRACT_PROMPT.version,
        )
        response = ExtractResponse.model_validate(normalize_response(result.data))
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


def normalize_response(data: object) -> dict[str, Any]:
    """Fold a real model's answer onto the stage-2 schema before validation.

    The scripted stand-in answers in exactly the schema's shape; a real model does
    not. It names the list of delivered fields ``fields``, puts ``field_name`` on the
    requirement instead of inside a condition, invents requirement types, and adds a
    ``description``. None of that changes what it read, so this folds the answer onto
    the schema instead of rejecting the whole section. Everything here is renaming
    and dropping: no value is compared or computed (ADR-001).

    Args:
        data: The JSON object the model returned, or anything else.

    Returns:
        A dictionary that ``ExtractResponse`` will validate, or that fails for a reason
        a rename could not fix.
    """
    if not isinstance(data, dict):
        return {"requirements": []}
    raw = data.get("requirements")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return {"requirements": []}
    requirements = [_normalize_requirement(item) for item in raw if isinstance(item, dict)]
    return {"requirements": [item for item in requirements if item is not None]}


def normalize_elements(data: object) -> dict[str, Any]:
    """Fold a real model's stage-3 answer onto the schema before validation.

    Same renaming and dropping as :func:`normalize_response`, for config elements: an
    element is a requirement plus ``json_path``, ``is_technical`` and ``description``.

    Args:
        data: The JSON object the model returned, or anything else.

    Returns:
        A dictionary for ``DescribeResponse`` to validate.
    """
    if not isinstance(data, dict):
        return {"elements": []}
    raw = data.get("elements")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return {"elements": []}
    elements: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = item.get("json_path", item.get("path"))
        if not isinstance(path, str) or not path:
            continue
        technical = bool(item.get("is_technical", False))
        declared = item.get("req_type", item.get("type"))
        element: dict[str, Any] = {
            "json_path": path,
            "is_technical": technical,
            "description": str(item.get("description", "")),
        }
        if technical or declared is None:
            element["req_type"] = None
        else:
            folded = _normalize_requirement(item) or {}
            for key in ("req_type", "conditions", "values", "mode", "steps", "quantity"):
                if key in folded:
                    element[key] = folded[key]
        confidence = item.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            element["confidence"] = min(1.0, max(0.0, float(confidence)))
        elements.append(element)
    return {"elements": elements}


def _normalize_requirement(item: dict[str, Any]) -> dict[str, Any] | None:
    """Fold one requirement onto the schema; ``None`` when it has no usable type."""
    out: dict[str, Any] = {}
    req_type = str(item.get("req_type") or item.get("type") or "").strip().lower()
    req_type = _REQ_TYPE_ALIASES.get(req_type, req_type)
    if req_type not in _VALID_REQ_TYPES:
        _LOG.info("stage 2: requirement type %r folded to other", req_type)
        req_type = "other"
    out["req_type"] = req_type

    for key in _VALUE_SYNONYMS:
        if key in item:
            out["values"] = _as_str_list(item[key])
            break

    conditions = item.get("conditions")
    if isinstance(conditions, dict):
        conditions = [conditions]
    normalized_conditions = (
        [_normalize_condition(c) for c in conditions if isinstance(c, dict)]
        if isinstance(conditions, list)
        else []
    )
    # A condition written flat on the requirement itself.
    flat_field = next((item[k] for k in _FIELD_SYNONYMS if item.get(k)), None)
    if flat_field is not None and not normalized_conditions and "operator" in item:
        normalized_conditions = [_normalize_condition(item)]
    elif flat_field is not None and req_type == "value_set" and "values" in out:
        # "field_name: state, values: [...]" is an "in"/"not_in" condition on that field.
        operator = "not_in" if str(item.get("mode", "")).lower() == "exclude" else "in"
        normalized_conditions = [
            {"field_name": str(flat_field), "operator": operator, "value": out["values"]}
        ]
    out["conditions"] = [c for c in normalized_conditions if c is not None]

    if "steps" in item:
        out["steps"] = _as_str_list(item["steps"])
    mode = item.get("mode")
    if isinstance(mode, str) and mode.strip().lower() in ("include", "exclude"):
        out["mode"] = mode.strip().lower()
    quantity = item.get("quantity", item.get("count"))
    if isinstance(quantity, (int, float)) and not isinstance(quantity, bool):
        out["quantity"] = float(quantity)
    elif isinstance(quantity, str):
        try:
            out["quantity"] = float(parse_number(quantity))
        except (ValueError, TypeError):
            pass
    for key in ("action", "applies_to", "source_text"):
        if isinstance(item.get(key), str):
            out[key] = item[key]
    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        out["confidence"] = min(1.0, max(0.0, float(confidence)))
    return out


def _normalize_condition(item: dict[str, Any]) -> dict[str, Any] | None:
    """Fold one condition onto the schema; ``None`` when it names no field."""
    field = next((item[k] for k in _FIELD_SYNONYMS if item.get(k)), None)
    if field is None:
        return None
    operator = str(item.get("operator", item.get("op", "="))).strip().lower()
    operator = _OPERATOR_ALIASES.get(operator, operator)
    if operator not in _VALID_OPERATORS:
        _LOG.info("stage 2: operator %r folded to =", operator)
        operator = "="
    value = item.get("value", item.get("threshold", item.get("values")))
    if isinstance(value, list):
        value = [_scalar(v) for v in value]
    else:
        value = _scalar(value)
    return {"field_name": str(field), "operator": operator, "value": value}


def _scalar(value: object) -> float | int | str | None:
    """Coerce one condition value: booleans become the strings the prompts ask for."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def _as_str_list(value: object) -> list[str]:
    """Coerce a model's list-ish value into a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return []


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
