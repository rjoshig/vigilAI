"""Stage 3: describe one ETL config block in requirement vocabulary.

Config schemas vary by job, so the model states what a block *does* using the same
vocabulary stage 2 produces. That shared vocabulary is what lets stage 4 compare a
requirement with an element, and stage 5 compare their values in code (ADR-001).
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import DescribeResponse

__all__ = ["DESCRIBE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "2"

_SYSTEM: Final = """\
You read one block of an ETL configuration file and say what it does, using the same \
vocabulary used for requirements.

Rules you must follow:
- Describe only this block. Do not guess at the rest of the configuration.
- Do not judge whether the block is correct, and do not compare it with anything. \
Another system does that.
- Mark the block is_technical when it configures plumbing rather than business rules: \
connections, file paths, logging, scheduling, retries, runtime tuning.
- Give a confidence between 0 and 1 for how sure you are of your reading.
- Answer with a single JSON object and nothing else. No prose, no code fence.

Requirement types: criteria, geography, value_set, attributes, waterfall, quantity, other.
A technical block has req_type null.

Business rules that are easy to mistake for plumbing:
- A list of processing steps in order (pipeline, stages, steps) is waterfall, with the \
steps copied in order.
- A record count to read or deliver is quantity.
- A suppression or exclusion flag that is switched on (deceased, OFAC, bankruptcy, \
opt-out) is criteria: one condition on that flag, operator "=", value "true", \
action "reject". A flag switched off is technical.
- A list of output fields is attributes with mode include.
- A dedupe key, a source table, a driver, and metadata are technical.

The answer has exactly this shape and no other keys anywhere:
{"elements": [ {element}, ... ]}
An element has only these keys: json_path, req_type, is_technical, description, \
conditions (a list of {"field_name", "operator", "value"}), values (a list of strings), \
mode ("include" or "exclude"), steps (a list of strings), quantity (a number), \
confidence (0 to 1). Do not add name, field, fields, id, or any other key.
"""

_EXAMPLES: Final = """\
Example 1
Block:
filters[0] = {"field": "ST", "op": "in", "value": ["IL", "AZ", "TX"]}
Answer:
{"elements": [{"json_path": "filters[0]", "req_type": "geography", \
"values": ["IL", "AZ", "TX"], "mode": "include", "is_technical": false, \
"description": "Keeps only records whose state is IL, AZ, or TX.", "confidence": 0.97}]}

Example 2
Block:
rules.score_v3 = {"field": "SCORE_V3", "min": 750, "op": ">="}
Answer:
{"elements": [{"json_path": "rules.score_v3", "req_type": "criteria", \
"conditions": [{"field_name": "SCORE_V3", "operator": ">=", "value": 750}], \
"is_technical": false, "description": "Accepts records whose V3 score is at least 750.", \
"confidence": 0.96}]}

Example 3
Block:
logging = {"destination": "stdout", "level": "INFO"}
Answer:
{"elements": [{"json_path": "logging", "req_type": null, "is_technical": true, \
"description": "Sets log verbosity and destination.", "confidence": 0.99}]}

Example 4
Block:
pipeline = {"steps": ["input", "geography", "score", "dedupe"]}
Answer:
{"elements": [{"json_path": "pipeline", "req_type": "waterfall", \
"steps": ["input", "geography", "score", "dedupe"], "is_technical": false, \
"description": "Runs the steps in this order.", "confidence": 0.96}]}

Example 5
Block:
suppressions = {"deceased": true, "ofac": false}
Answer:
{"elements": [{"json_path": "suppressions.deceased", "req_type": "criteria", \
"conditions": [{"field_name": "deceased", "operator": "=", "value": "true"}], \
"is_technical": false, "description": "Rejects records flagged as deceased.", \
"confidence": 0.95}, {"json_path": "suppressions.ofac", "req_type": null, \
"is_technical": true, "description": "OFAC suppression is switched off.", \
"confidence": 0.95}]}
"""

_TEMPLATE: Final = """\
{examples}
Now do the same for this block.

Block:
$block

Answer:"""


DESCRIBE_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="s3_describe",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("{examples}", _EXAMPLES),
        schema=DescribeResponse,
    )
)
