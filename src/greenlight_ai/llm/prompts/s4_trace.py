"""Stage 4: judge whether one config element implements one requirement.

Code shortlists candidates by type and field alias and links exact matches without a
call; the judge sees only the unclear pairs (``docs/design.md`` "LLM cost controls").
The question is deliberately narrow: does this element implement this requirement? The
model recognises equivalents such as "reject age < 21" and "accept age >= 21", but it
never decides whether the values match. Code does that in stage 5 (ADR-001).
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import TraceResponse

__all__ = ["TRACE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
You are given one requirement from a specification and one element from an ETL \
configuration. Answer one question: does this element implement this requirement?

Verdicts:
- implemented: the element addresses this requirement, even if the values differ.
- partial: the element addresses part of the requirement but not all of it.
- contradicts: the element addresses the requirement and does the opposite.
- not_related: the element addresses something else entirely.

Rules you must follow:
- Judge the subject matter, not the numbers. If the requirement is about a score \
threshold and the element sets a score threshold, that is "implemented" even when the \
two thresholds differ. Another system compares the values.
- Treat equivalent phrasings as the same subject: "reject when age is under 21" and \
"accept when age is at least 21" are both about the age threshold.
- Do not do arithmetic and do not say which value is right.
- Give one short sentence of reasoning and a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Requirement: criteria — score must be at least 755.
Element: rules.score_v3 — accepts records whose V3 score is at least 750.
Answer:
{"verdict": "implemented", "reason": "Both set the minimum V3 score for acceptance.", \
"confidence": 0.95}

Example 2
Requirement: criteria — reject any consumer whose age is under 21.
Element: rules.age — accepts records whose age is at least 21.
Answer:
{"verdict": "implemented", "reason": "Rejecting under 21 and accepting 21 and over are \
the same rule stated from opposite sides.", "confidence": 0.93}

Example 3
Requirement: exclusion — exclude any consumer with a bankruptcy in the last 24 months.
Element: suppressions.ofac — suppresses consumers on the OFAC list.
Answer:
{"verdict": "not_related", "reason": "OFAC suppression is a sanctions check, not a \
bankruptcy exclusion.", "confidence": 0.9}
"""

_TEMPLATE: Final = """\
{examples}
Now answer for this pair.

Requirement: $requirement
Element: $element

Answer:"""


TRACE_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="s4_trace",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("{examples}", _EXAMPLES),
        schema=TraceResponse,
    )
)
