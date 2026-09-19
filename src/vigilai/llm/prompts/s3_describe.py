"""Stage 3: describe one ETL config block in requirement vocabulary.

Config schemas vary by job, so the model states what a block *does* using the same
vocabulary stage 2 produces. That shared vocabulary is what lets stage 4 compare a
requirement with an element, and stage 5 compare their values in code (ADR-001).
"""

from __future__ import annotations

from typing import Final

from vigilai.llm.prompts.registry import Prompt, register
from vigilai.llm.prompts.schemas import DescribeResponse

__all__ = ["DESCRIBE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

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
