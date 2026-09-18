#!/usr/bin/env python3
"""A scripted stand-in for a competent model, for the golden set and the test suite.

Phase 2 is built and validated against ``LLM_PROVIDER=mock`` (ADR-014), but a mock that
returns empty payloads cannot exercise the pipeline: every stage would have nothing to
work with and a passing test would mean nothing. This module answers each LLM stage by
*reading the prompt*, the way a competent model would for the synthetic fixtures.

It is deliberately not part of ``src/vigilai/``: it is evaluation tooling, and shipping
a fixture-aware responder inside the product would let a real deployment accidentally
depend on it. It never consults a case's oracle, so a test can still catch the pipeline
drawing a wrong conclusion from a right answer.
"""

from __future__ import annotations

import json
import re
from typing import Any

from vigilai.llm import LLMSettings, MockClient
from vigilai.rules.normalize import AliasTable

__all__ = [
    "FIXTURE_ALIASES",
    "extract_responder",
    "describe_responder",
    "trace_responder",
    "build_client",
]

#: Aliases the synthetic fixtures need: the OSL writes prose, the config writes columns.
FIXTURE_ALIASES = AliasTable.from_mapping(
    {
        "score": ["SCORE_V3", "V3 score", "credit score"],
        "age": ["AGE", "consumer age"],
        "state": ["ST", "geography"],
        "revolving_utilization": ["REV_UTIL", "utilization", "revolving utilization"],
        "open_trades": ["OPEN_TRADES", "open trades"],
    }
)

_OPERATOR_BY_PHRASE = {
    "at least": ">=",
    "greater than": ">",
    "at most": "<=",
    "below": "<",
}


def extract_responder(_system: str, user: str) -> str:
    """Answer stage 2 by reading the OSL section in the prompt.

    Mirrors what a competent model returns for the synthetic OSL: geography from the
    prose, criteria from the table, attributes from the numbered list, waterfall from
    the processing-order sentence.
    """
    section = user.split("Section:\n")[-1].split("\n\nAnswer:")[0]
    requirements: list[dict[str, Any]] = []

    if "Geography" in section:
        states = re.findall(r"\b(Illinois|Arizona|Texas|Nevada|Ohio)\b", section)
        if states:
            requirements.append(
                {
                    "req_type": "geography",
                    "values": states,
                    "mode": "include",
                    "action": "accept",
                    "applies_to": "all",
                    "source_text": section.strip().splitlines()[-1],
                    "confidence": 0.96,
                }
            )

    for label, phrase, threshold in re.findall(
        r"^(\w[\w ]*?) \| (at least|greater than|at most|below) \| ([\d.]+)$",
        section,
        re.MULTILINE,
    ):
        requirements.append(
            {
                "req_type": "criteria",
                "conditions": [
                    {
                        "field_name": label.strip(),
                        "operator": _OPERATOR_BY_PHRASE[phrase],
                        "value": float(threshold),
                    }
                ],
                "action": "accept",
                "applies_to": "accepts",
                "source_text": f"{label} | {phrase} | {threshold}",
                "confidence": 0.97,
            }
        )

    attributes = re.findall(r"^\d+\. ([A-Z_0-9]+)$", section, re.MULTILINE)
    if attributes and "Output attributes" in section:
        requirements.append(
            {
                "req_type": "attributes",
                "values": attributes,
                "mode": "include",
                "action": "accept",
                "applies_to": "accepts",
                "source_text": "Deliver the following attributes.",
                "confidence": 0.95,
            }
        )

    order = re.search(r"Process in this order: ([^.]+)\.", section)
    if order:
        steps = [s.strip() for s in order.group(1).replace(", then", ",").split(",")]
        requirements.append(
            {
                "req_type": "waterfall",
                "steps": steps,
                "action": "pass",
                "applies_to": "all",
                "source_text": order.group(0),
                "confidence": 0.94,
            }
        )

    return json.dumps({"requirements": requirements})


def describe_responder(_system: str, user: str) -> str:
    """Answer stage 3 by reading the config block in the prompt."""
    block = user.split("Block:\n")[-1].split("\n\nAnswer:")[0].strip()
    path, _, payload = block.partition(" = ")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return json.dumps({"elements": [{"json_path": path, "is_technical": True}]})

    element: dict[str, Any] = {"json_path": path, "is_technical": False, "confidence": 0.96}

    if isinstance(value, dict) and value.get("op") == "in":
        element.update(
            {
                "req_type": "geography" if value.get("field") == "ST" else "value_set",
                "values": list(value.get("value", [])),
                "mode": "include",
                "description": f"Keeps only records whose {value.get('field')} is in the list.",
            }
        )
    elif isinstance(value, dict) and "op" in value:
        # A threshold is written as "min"/"max" in the rules block and as a plain
        # "value" in a filter; a competent reader handles both spellings.
        bound = value.get("min", value.get("max", value.get("value")))
        element.update(
            {
                "req_type": "criteria",
                "conditions": [
                    {
                        "field_name": value.get("field", path.split(".")[-1]),
                        "operator": value["op"],
                        "value": bound,
                    }
                ],
                "description": f"Bounds {value.get('field')} at {bound}.",
            }
        )
    elif isinstance(value, dict) and "fields" in value:
        element.update(
            {
                "req_type": "attributes",
                "values": list(value["fields"]),
                "mode": "include",
                "description": "The delivered attribute list.",
            }
        )
    elif isinstance(value, dict) and "steps" in value:
        element.update(
            {
                "req_type": "waterfall",
                "steps": list(value["steps"]),
                "description": "The processing order.",
            }
        )
    elif isinstance(value, dict) and "count" in value:
        element.update(
            {
                "req_type": "quantity",
                "quantity": value["count"],
                "description": "The input record count.",
            }
        )
    else:
        element.update({"is_technical": True, "description": "Not a business rule."})

    return json.dumps({"elements": [element]})


#: Requirement types with exactly one subject: matching the type is enough to decide
#: that two items are about the same thing.
_SINGLE_SUBJECT_TYPES = ("geography", "waterfall", "quantity", "attributes")

#: Attributes the synthetic cases constrain, used to tell one criteria rule from another.
_SUBJECTS = ("score", "age", "util", "trades", "state")


def trace_responder(_system: str, user: str) -> str:
    """Answer stage 4 the way the prompt instructs: subject matter, never values.

    A criteria requirement about the score is *not* implemented by a criteria element
    about age, so matching on the requirement type alone is not enough; the attribute
    has to agree too.
    """
    requirement = user.split("Requirement: ")[-1].split("\n")[0].lower()
    element = user.split("Element: ")[-1].split("\n")[0].lower()
    req_type = requirement.split(" — ")[0].strip()

    if req_type in _SINGLE_SUBJECT_TYPES and req_type in element:
        return json.dumps(
            {"verdict": "implemented", "reason": "Same subject matter.", "confidence": 0.9}
        )

    if req_type == "criteria" and "criteria" in element:
        for subject in _SUBJECTS:
            if subject in requirement and subject in element:
                return json.dumps(
                    {
                        "verdict": "implemented",
                        "reason": f"Both constrain the {subject}.",
                        "confidence": 0.88,
                    }
                )

    return json.dumps({"verdict": "not_related", "reason": "Different subject.", "confidence": 0.8})


def build_client(settings: LLMSettings | None = None, **kwargs: Any) -> MockClient:
    """Build a mock client wired with the scripted responders.

    Args:
        settings: Adapter settings; the mock defaults are used when omitted.
        **kwargs: Passed to :class:`~vigilai.llm.mock.MockClient`, e.g. a shared cache.

    Returns:
        A client that answers every LLM stage without a network call.
    """
    client = MockClient(settings or LLMSettings(), **kwargs)
    client.register("s2_extract", extract_responder)
    client.register("s3_describe", describe_responder)
    client.register("s4_trace", trace_responder)
    client.register_text(
        "s8_verify", json.dumps({"agreed": True, "reason": "Confirmed.", "confidence": 0.9})
    )
    return client
