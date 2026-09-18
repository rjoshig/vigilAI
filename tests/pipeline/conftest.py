"""Fixtures for pipeline tests.

The mock client is driven by responders that answer as a competent model would for the
synthetic cases, so the pipeline is exercised end to end without a network (ADR-014).
The responders read the prompt and answer from it; they never consult the oracle, so a
test can still catch the pipeline drawing a wrong conclusion from a right answer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from vigilai.llm import LLMSettings, MockClient
from vigilai.pipeline.context import RunContext
from vigilai.rules.normalize import AliasTable

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


def _extract_responder(_system: str, user: str) -> str:
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


def _describe_responder(_system: str, user: str) -> str:
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
        bound = value.get("min", value.get("max"))
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


def _trace_responder(_system: str, user: str) -> str:
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


@pytest.fixture()
def client() -> MockClient:
    """A mock client wired with responders for every LLM stage."""
    mock = MockClient(LLMSettings())
    mock.register("s2_extract", _extract_responder)
    mock.register("s3_describe", _describe_responder)
    mock.register("s4_trace", _trace_responder)
    return mock


@pytest.fixture()
def make_context(fixtures_root: Path, cases: dict[str, Any], client: MockClient):
    """Build a run context for a named fixture case."""

    def build(case_name: str) -> RunContext:
        case = cases[case_name]
        return RunContext(
            run_id=f"TEST-{case_name}",
            osl_path=fixtures_root / case["osl"],
            config_path=fixtures_root / case["config"],
            report_paths={
                kind: fixtures_root / path  # type: ignore[misc]
                for kind, path in case["reports"].items()
            },
            client=client,
            aliases=FIXTURE_ALIASES,
        )

    return build
