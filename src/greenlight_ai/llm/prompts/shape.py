"""What the delivery's numbers look like to a reader (Phase 6.21c).

The second half of the anomaly check, and the narrowest question in the product after
the name locator. Code has already compared this delivery against its own history and
said what moved; this asks a different question — *does anything here look odd on its
own terms?* — which is the one thing a history cannot answer for a configuration's
first deliveries, and the one thing a rule cannot answer for a case nobody anticipated.

**It is shown aggregates and nothing else** (ADR-003). A null rate, a minimum, a
maximum, a mean. Never a row, never which record held the minimum, never a value that
is not already a summary of many. That is what makes the call safe to make on every
delivery.

**It grades nothing.** It is not asked whether the delivery is correct, whether a
requirement is met, or how serious anything is. Code checks that every attribute it
names was one it was shown, applies a confidence floor, and raises a **review** item —
a question for a person, never a failure (ADR-001).

The expected answer is an empty list, and the prompt says so, because a model asked
"what is unusual here" will find something.
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import ShapeReading

__all__ = ["SHAPE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
A quality-control system has summarised a credit-data delivery: for each attribute it \
delivered, how often the value was missing, the smallest and largest values, and the \
average. You are being asked to read those summaries and say whether any of them look \
unusual for a delivery of this kind.

Rules you must follow:
- You are shown aggregate statistics only. No records, no individual values. Do not \
assume anything about the underlying data beyond what these summaries say.
- An empty answer is the expected one. Most deliveries have nothing odd about them, \
and saying so is a correct and useful answer, not a failure on your part.
- Name an attribute only when its numbers are odd on their face: a rate of missing \
values high enough to make a field unusable, a range that cannot be right for what the \
field is, an average that sits outside its own minimum and maximum.
- Quote the attribute name exactly as it was given to you. An attribute that is not in \
the list will be rejected.
- Do not say whether the delivery is correct, whether it meets a requirement, or how \
serious anything is. Say what you noticed; somebody else decides what it means.
- Do not compare against what you think is normal for the industry. Read what is in \
front of you.
- Give a confidence between 0 and 1 for each one, and one short sentence overall.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Attributes:
- SCORE_V3: missing 0.1%, min 300, max 850, mean 706
- AGE: missing 0.0%, min 21, max 94, mean 48
Answer:
{"unusual": [], "reason": "Both ranges and averages sit where these fields normally \
do, and almost nothing is missing."}

Example 2
Attributes:
- MORT_BAL: missing 61.4%, min 0, max 2100000, mean 184320
- AGE: missing 0.0%, min 21, max 94, mean 48
Answer:
{"unusual": [{"attribute": "MORT_BAL", "observation": "Missing for most of the \
delivery, which leaves the field unusable for anyone relying on it.", "confidence": \
0.82}], "reason": "One field is absent for the majority of records."}

Example 3
Attributes:
- OPEN_TRADES: missing 0.0%, min 2, max 41, mean 58
Answer:
{"unusual": [{"attribute": "OPEN_TRADES", "observation": "The average is above the \
largest value reported, which cannot both be true.", "confidence": 0.91}], "reason": \
"One field's summary contradicts itself."}
"""

_TEMPLATE: Final = """\
${examples}
Now read this delivery.

Attributes:
${attributes}

Answer:"""


SHAPE_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="shape_reading",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=ShapeReading,
    )
)
