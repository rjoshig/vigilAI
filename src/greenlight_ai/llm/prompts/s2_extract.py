"""Stage 2: extract requirements from one OSL section or table.

One call per section keeps the input small and the output small, which is what makes a
mid-size model reliable (``docs/design.md`` "Making a mid-size model reliable"). The
model reads and judges meaning; it never compares or computes (ADR-001).
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import ExtractResponse

__all__ = ["EXTRACT_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "4"

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
- attributes: which fields must be delivered. A section may name the fields one by \
one, or name a product code that stands for a set of them ("all attributes from ABC", \
"the ABC package", "product code ABC"). When it names a code, put the code in \
product_codes and leave values empty; do not try to list what the code contains. What \
a code contains is looked up, not read.
- waterfall: the order in which processing steps run.
- quantity: how many records must be delivered. The size of the input population, \
the pull date, and other background about where the data comes from are context, \
not requirements: do not report them.
- other: an instruction that fits none of the above.

An exclusion of records that carry a flag or appear on a list (deceased, OFAC, \
bankruptcy, opt-out) is criteria: one condition on that flag, operator "=", value \
"true", action "reject". Use value_set only when the text lists the specific values \
of an attribute that are allowed or excluded.

For criteria, express the condition exactly as written: "at least 755" is \
operator ">=" with value 755; "below 60 percent" is operator "<" with value 0.6; \
"reject if age under 21" is operator "<" with value 21 and action "reject".
For geography and value_set, set mode to "include" or "exclude" and list the values.

The answer has exactly this shape and no other keys anywhere:
{"requirements": [ {requirement}, ... ]}
A requirement has only these keys:
- req_type: one of criteria, geography, value_set, attributes, waterfall, quantity, other
- conditions: a list of {"field_name": str, "operator": str, "value": number or string \
or list}; the operator is one of <, <=, >, >=, =, !=, in, not_in, between, is_null, not_null
- values: a list of strings (the states, allowed values, or delivered field names)
- product_codes: a list of strings (attributes only; the codes the section names \
instead of listing fields). Omit it when the section lists fields directly.
- mode: "include" or "exclude", or omit it
- steps: a list of strings, in order (waterfall only)
- quantity: a number, or omit it
- action: one of accept, reject, tag, pass
- applies_to: one of all, accepts, rejects
- source_text: a string
- confidence: a number between 0 and 1
Never invent what a product code contains, and never put a code in values. A code is \
an identifier the section quotes; the attributes behind it are looked up elsewhere.
Do not add description, name, field, fields, id, or any other key. A field the \
requirement is about goes inside a condition as field_name; delivered field names go in \
values. A section with no requirements answers {"requirements": []}.
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

Example 4
Section:
5 Output attributes
Deliver the following fields for every accepted record: account_id, score, state.
Answer:
{"requirements": [{"req_type": "attributes", "values": ["account_id", "score", "state"], \
"action": "accept", "applies_to": "accepts", \
"source_text": "Deliver the following fields for every accepted record: account_id, \
score, state.", "confidence": 0.95}]}

Example 4b
Section:
5.1 Output attributes
Deliver all attributes from product code ABC for every accepted record.
Answer:
{"requirements": [{"req_type": "attributes", "product_codes": ["ABC"], \
"action": "accept", "applies_to": "accepts", \
"source_text": "Deliver all attributes from product code ABC for every accepted \
record.", "confidence": 0.93}]}

Example 5
Section:
7 Exclusions
Exclude any consumer recorded as deceased. Exclude any account whose type is C or D.
Answer:
{"requirements": [{"req_type": "criteria", "conditions": [{"field_name": "deceased", \
"operator": "=", "value": "true"}], "action": "reject", "applies_to": "all", \
"source_text": "Exclude any consumer recorded as deceased.", "confidence": 0.95}, \
{"req_type": "value_set", "conditions": [{"field_name": "account type", \
"operator": "in", "value": ["C", "D"]}], "values": ["C", "D"], "mode": "exclude", \
"action": "reject", "applies_to": "all", \
"source_text": "Exclude any account whose type is C or D.", "confidence": 0.95}]}

Example 6
Section:
2 Population
The input population is 250,000 consumer records drawn from the prescreen universe as \
of the pull date.
Answer:
{"requirements": []}
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
