"""Stage 2: extract requirements from one OSL section or table.

One call per section keeps the input small and the output small, which is what makes a
mid-size model reliable (``docs/design.md`` "Making a mid-size model reliable"). The
model reads and judges meaning; it never compares or computes (ADR-001).
"""

from __future__ import annotations

from typing import Final

from vigilai.llm.prompts.registry import Prompt, register
from vigilai.llm.prompts.schemas import ExtractResponse

__all__ = ["EXTRACT_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
You read one section of an Order Specification Letter (OSL) and report the requirements \
it states. The OSL is the source of truth for a credit-data delivery.

Rules you must follow:
- Report only what the section says. Never infer a requirement the text does not state.
- Do not compare values, do arithmetic, or judge whether anything is correct. Another \
system does that. Your only job is to say what the text requires.
- Copy the wording that supports each requirement into source_text, verbatim.
- Give each requirement a confidence between 0 and 1: how sure you are that you read the \
text correctly. Use a value below 0.7 when the wording is ambiguous.
- Answer with a single JSON object and nothing else. No prose, no code fence.

Requirement types:
- criteria: a numeric threshold on an attribute, e.g. score at least 755.
- geography: which states are in or out of scope.
- value_set: which values of some attribute are allowed or excluded.
- attributes: which fields must be delivered.
- waterfall: the order in which processing steps run.
- quantity: a count of records to deliver.
- other: an instruction that fits none of the above.

For criteria, express the condition exactly as written: "at least 755" is \
operator ">=" with value 755; "below 60 percent" is operator "<" with value 0.6; \
"reject if age under 21" is operator "<" with value 21 and action "reject".
For geography and value_set, set mode to "include" or "exclude" and list the values.
"""

_EXAMPLES: Final = """\
Example 1
Section:
3 Geography
Include only consumers whose current address is in Illinois or Arizona. No other states \
are in scope for this campaign.
Answer:
{"requirements": [{"req_type": "geography", "values": ["Illinois", "Arizona"], \
"mode": "include", "action": "accept", "applies_to": "all", \
"source_text": "Include only consumers whose current address is in Illinois or Arizona.", \
"confidence": 0.96}]}

Example 2
Section:
4 Credit criteria
Attribute | Condition | Threshold
score | at least | 755
age | at least | 21
Answer:
{"requirements": [{"req_type": "criteria", "conditions": [{"field_name": "score", \
"operator": ">=", "value": 755}], "action": "accept", "applies_to": "accepts", \
"source_text": "score | at least | 755", "confidence": 0.97}, {"req_type": "criteria", \
"conditions": [{"field_name": "age", "operator": ">=", "value": 21}], "action": "accept", \
"applies_to": "accepts", "source_text": "age | at least | 21", "confidence": 0.97}]}

Example 3
Section:
6 Processing order
Process in this order: geography, then score, then age, then exclusions, then dedupe. \
All input records must be accounted for as either accepted or rejected.
Answer:
{"requirements": [{"req_type": "waterfall", "steps": ["geography", "score", "age", \
"exclusions", "dedupe"], "action": "pass", "applies_to": "all", \
"source_text": "Process in this order: geography, then score, then age, then exclusions, \
then dedupe.", "confidence": 0.94}]}
"""

_TEMPLATE: Final = """\
{examples}
Now do the same for this section.

Section:
$section

Answer:"""


EXTRACT_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="s2_extract",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("{examples}", _EXAMPLES),
        schema=ExtractResponse,
    )
)
