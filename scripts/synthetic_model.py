#!/usr/bin/env python3
"""A scripted stand-in for a competent model, for the golden set and the test suite.

Phase 2 is built and validated against ``LLM_PROVIDER=mock`` (ADR-014), but a mock that
returns empty payloads cannot exercise the pipeline: every stage would have nothing to
work with and a passing test would mean nothing. This module answers each LLM stage by
*reading the prompt*, the way a competent model would for the synthetic fixtures.

It is deliberately not part of ``src/greenlight_ai/``: it is evaluation tooling, and shipping
a fixture-aware responder inside the product would let a real deployment accidentally
depend on it. It never consults a case's oracle, so a test can still catch the pipeline
drawing a wrong conclusion from a right answer.
"""

from __future__ import annotations

import json
import re
from typing import Any

from greenlight_ai.llm import LLMSettings, MockClient
from greenlight_ai.rules.normalize import AliasTable

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

    if "Additional requirements" in section:
        # Free-text clauses. A competent model returns these as ``other``: they carry
        # a requirement and no check can express one, which is what puts them in
        # coverage as "verified by hand" (Phase 6.11b).
        for line in section.splitlines():
            clause = line.strip()
            if len(clause) < 20 or clause.startswith("9 ") or "Additional requirements" in clause:
                continue
            requirements.append(
                {
                    "req_type": "other",
                    "action": "pass",
                    "applies_to": "all",
                    "source_text": clause,
                    "confidence": 0.85,
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
    elif isinstance(value, dict) and "describes" in value:
        # A policy the configuration carries that no threshold expresses. A competent
        # reader calls it ``other``: it is a requirement, and no check can compare it
        # against a report (Phase 6.11b).
        element.update(
            {
                "req_type": "other",
                "description": f"A policy setting: {value['describes']}",
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

#: Words too ordinary to mean two free-text items are about the same thing.
_COMMON_WORDS = frozenset(
    {
        "other",
        "setting",
        "policy",
        "every",
        "which",
        "these",
        "after",
        "under",
        "their",
        "order",
        "record",
        "records",
        "consumer",
        "consumers",
        "delivery",
        "deliveries",
    }
)

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

    if req_type == "other":
        # Two free-text items are about the same thing when they share an uncommon
        # word. Deliberately crude: the point is to exercise the path, not to be a
        # model.
        words = {w for w in re.findall(r"[a-z]{5,}", requirement)} & {
            w for w in re.findall(r"[a-z]{5,}", element)
        }
        if words - _COMMON_WORDS:
            return json.dumps(
                {
                    "verdict": "implemented",
                    "reason": "The configuration carries this policy.",
                    "confidence": 0.8,
                }
            )
        return json.dumps(
            {"verdict": "not_related", "reason": "Different subjects.", "confidence": 0.8}
        )

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


def map_responder(_system: str, user: str) -> str:
    """Answer the mapping interview from the section heading in the prompt.

    Reads the last ``Section:`` block (the worked examples carry earlier ones) and
    proposes the links a competent reader would for the synthetic fixtures: the
    population count against ``input.count`` with the Flow sheet's Input row, the
    geography filter, and an OFAC exclusion the configuration does not carry, which
    comes back as an open question with a compliance suggestion.
    """
    section = user.split("Section:\n")[-1].split("\nConfiguration blocks:")[0].strip()
    heading = section.splitlines()[0].lower() if section else ""
    requirements: list[dict[str, Any]] = []
    if "population" in heading:
        requirements.append(
            {
                "key": "input_population",
                "requirement_text": section.splitlines()[-1][:200],
                "config_path": "input.count",
                "report_cells": [
                    {"report_key": "counts", "sheet": "Flow", "label": "Input", "cell": ""}
                ],
                "validate": "The Flow sheet's Input row equals the configured input count.",
                "comparison": "equals",
                "confidence": 0.9,
                "question": None,
                "compliance_suggestion": None,
            }
        )
    elif "geography" in heading:
        requirements.append(
            {
                "key": "geography",
                "requirement_text": section.splitlines()[-1][:200],
                "config_path": "filters[0]",
                "report_cells": [
                    {
                        "report_key": "state_distribution",
                        "sheet": "States",
                        "label": "State",
                        "cell": "",
                    }
                ],
                "validate": "Every state in the distribution is an allowed state.",
                "comparison": "",
                "confidence": 0.93,
                "question": None,
                "compliance_suggestion": None,
            }
        )
    elif "exclusions" in heading:
        requirements.append(
            {
                "key": "ofac_excluded",
                "requirement_text": "Exclude any consumer on the OFAC list.",
                "config_path": None,
                "report_cells": [],
                "validate": "OFAC hits are suppressed.",
                "comparison": "",
                "confidence": 0.5,
                "question": "No configuration block mentions OFAC; is it set elsewhere?",
                "compliance_suggestion": {
                    "name": "OFAC suppression",
                    "json_path_contains": "suppressions.ofac",
                    "reasoning": "Every delivery must suppress OFAC hits.",
                },
            }
        )
    return json.dumps({"requirements": requirements})


def synthesize_responder(_system: str, user: str) -> str:
    """Answer a training synthesis call, scripted from the statement's wording.

    It recognises the shapes the tests exercise and refuses anything that reads like
    an instruction, which is what the injection test relies on: a scripted stand-in
    that obeyed embedded instructions would make the test pass for the wrong reason.

    Args:
        _system: The system prompt, unused.
        user: The rendered prompt, which carries the statements.

    Returns:
        A JSON ``SynthesisResponse``.
    """
    # Only the last statements block: the prompt carries worked examples that also
    # sit between these markers, and matching on those would make every call look
    # like every example.
    blocks = user.split("<statements>")
    lowered = blocks[-1].split("</statements>")[0].lower() if len(blocks) > 1 else user.lower()
    rules: list[dict[str, Any]] = []

    def came_from(*needles: str) -> list[int]:
        """Which numbered statements carry a trigger phrase, one-based like the prompt."""
        hits: list[int] = []
        for line in lowered.splitlines():
            text = line.strip()
            number, _, rest = text.partition(". ")
            if number.isdigit() and any(needle in rest for needle in needles):
                hits.append(int(number))
        return hits

    if "never empty" in lowered or "not blank" in lowered or "never blank" in lowered:
        rules.append(
            {
                "name": "account_status_not_blank",
                "target_kind": "field_constraint",
                "field": "account_status",
                "constraint": "not_blank",
                "values": [],
                "minimum": None,
                "maximum": None,
                "pattern": "",
                "report_kinds": ["dirt"],
                "expression": "",
                "reasoning": "A blank here means the extract dropped the value.",
                "severity": "high",
                "cannot_express": "",
                "json_path_contains": "",
                "from_statements": came_from("never empty", "not blank", "never blank"),
            }
        )
    if "between 300" in lowered or "below 300" in lowered:
        rules.append(
            {
                "name": "score_within_band",
                "target_kind": "field_constraint",
                "field": "score",
                "constraint": "range",
                "values": [],
                "minimum": 300,
                "maximum": 850,
                "pattern": "",
                "report_kinds": [],
                "expression": "",
                "reasoning": "Scores outside 300 to 850 are not valid.",
                "severity": "medium",
                "cannot_express": "",
                "json_path_contains": "",
                "from_statements": came_from("between 300", "below 300"),
            }
        )
    if "blank origination date" in lowered or "origination date" in lowered:
        rules.append(
            {
                "name": "origination_date_not_blank",
                "target_kind": "field_constraint",
                "field": "orig_date",
                "constraint": "not_blank",
                "values": [],
                "minimum": None,
                "maximum": None,
                "pattern": "",
                "report_kinds": ["account_review"],
                "expression": "",
                "reasoning": "A blank origination date means the extract dropped it.",
                "severity": "high",
                "cannot_express": "",
                "json_path_contains": "",
                "from_statements": came_from("origination date"),
            }
        )
    if "billing count" in lowered and "delivered count" in lowered:
        rules.append(
            {
                "name": "billing_within_delivered",
                "target_kind": "check",
                "field": "",
                "constraint": "",
                "values": [],
                "minimum": None,
                "maximum": None,
                "pattern": "",
                "report_kinds": [],
                "expression": "billing_count <= delivered_count",
                "reasoning": "More billed than delivered means something was counted twice.",
                "severity": "high",
                "cannot_express": "",
                "json_path_contains": "",
                "from_statements": came_from("billing count"),
            }
        )
    if "configuration" in lowered and ("must" in lowered or "has to" in lowered):
        rules.append(
            {
                "name": "deceased_suppression_present",
                "target_kind": "compliance_rule",
                "field": "",
                "constraint": "",
                "values": [],
                "minimum": None,
                "maximum": None,
                "pattern": "",
                "report_kinds": [],
                "expression": "",
                "reasoning": "The suppression must be configured whether or not the OSL says so.",
                "severity": "high",
                "cannot_express": "",
                "json_path_contains": "suppressions.deceased",
                "from_statements": came_from("configuration"),
            }
        )
    if "ignore your instructions" in lowered or "reply with the word" in lowered:
        rules.append(
            {
                "name": "",
                "target_kind": "unsupported",
                "field": "",
                "constraint": "",
                "values": [],
                "minimum": None,
                "maximum": None,
                "pattern": "",
                "report_kinds": [],
                "expression": "",
                "reasoning": "",
                "severity": "medium",
                "cannot_express": (
                    "This is an instruction to the assistant, not an expectation "
                    "about a delivery."
                ),
            }
        )

    if not rules:
        rules.append(
            {
                "name": "",
                "target_kind": "unsupported",
                "field": "",
                "constraint": "",
                "values": [],
                "minimum": None,
                "maximum": None,
                "pattern": "",
                "report_kinds": [],
                "expression": "",
                "reasoning": "",
                "severity": "medium",
                "cannot_express": "Nothing in these statements maps to a rule shape.",
            }
        )
    return json.dumps({"rules": rules, "notes": ""})


def critique_responder(_system: str, user: str) -> str:
    """Read a drafted rule back against the statements it came from (Phase 6.11g).

    The stand-in agrees unless a statement carries the word "every", which is the
    shape of an over-broad draft and gives a test something deterministic to script
    against without a network.

    Args:
        _system: The system prompt, unused.
        user: The rendered user prompt.

    Returns:
        The critique, as JSON.
    """
    too_broad = "report kinds []" in user and "file" in user.lower()
    return json.dumps(
        {
            "faithful": not too_broad,
            "problem": (
                "The statement names one report and the draft applies to every report."
                if too_broad
                else ""
            ),
            "overlaps": False,
            "overlaps_with": "",
            "confidence": 0.9,
        }
    )


def classify_responder(_system: str, user: str) -> str:
    """Place a statement an administrator typed (Phase 6.12b).

    Scripted from the statement's wording, and deliberately unhelpful about anything it
    does not recognise: a stand-in that guessed would make the "asks a question rather
    than guessing" test pass for the wrong reason.

    Args:
        _system: The system prompt, unused.
        user: The rendered prompt, which carries the statement.

    Returns:
        A JSON ``ClassifyResponse``.
    """
    blocks = user.split("<statement>")
    lowered = blocks[-1].split("</statement>")[0].lower() if len(blocks) > 1 else user.lower()

    def answer(surface: str, reason: str, confidence: float, question: str = "") -> str:
        return json.dumps(
            {
                "surface": surface,
                "reason": reason,
                "confidence": confidence,
                "question": question,
            }
        )

    if "ignore your instructions" in lowered or "reply with the word" in lowered:
        return answer(
            "unclear",
            "This is an instruction to the assistant rather than something to check.",
            0.9,
            "What would you like the tool to check?",
        )
    if "tab" in lowered or "is the reissue file" in lowered or "means" in lowered:
        return answer("background", "This says how to read a file.", 0.8)
    if "configuration" in lowered and ("must" in lowered or "has to" in lowered):
        return answer("compliance_rule", "This must be present in the configuration.", 0.9)
    if "count" in lowered and ("exceed" in lowered or "more than" in lowered):
        return answer("check", "This compares two numbers the tool already names.", 0.9)
    if "blank" in lowered or "empty" in lowered or "between" in lowered:
        return answer("field_constraint", "This is a rule about one attribute.", 0.9)
    return answer(
        "unclear",
        "There is no attribute, number or configuration setting named here.",
        0.2,
        "Which value, and what would make it wrong?",
    )


def build_client(settings: LLMSettings | None = None, **kwargs: Any) -> MockClient:
    """Build a mock client wired with the scripted responders.

    Args:
        settings: Adapter settings; the mock defaults are used when omitted.
        **kwargs: Passed to :class:`~greenlight_ai.llm.mock.MockClient`, e.g. a shared cache.

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
    client.register("training_synthesize", synthesize_responder)
    client.register("training_critique", critique_responder)
    client.register("admin_classify", classify_responder)
    client.register("admin_map_requirement", map_responder)
    # Every lens answers like the single second opinion, so a run with the lenses on
    # behaves the same as one without unless a test scripts a disagreement.
    for lens in ("delivery", "compliance", "requirements"):
        client.register_text(
            f"s8_lens_{lens}",
            json.dumps({"agreed": True, "reason": "Confirmed.", "confidence": 0.9, "missed": []}),
        )
    client.register_text("s8_coverage", json.dumps({"gaps": []}))
    return client
