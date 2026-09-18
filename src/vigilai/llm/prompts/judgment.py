"""Judgment checks: for rules a formula cannot express.

The model receives only the named values and the admin's reasoning — never the reports
themselves — and returns pass, fail, or review (``docs/design.md`` "Configurable
checks"). Flagged "use sparingly" in the admin-ui, because a judgment check costs a call
on every run where an expression check costs nothing.
"""

from __future__ import annotations

from typing import Final

from vigilai.llm.prompts.registry import Prompt, register
from vigilai.llm.prompts.schemas import JudgmentResponse

__all__ = ["JUDGMENT_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
An administrator has written a rule that no formula can express, and a validation system \
has resolved the values it refers to. Say whether the delivery satisfies the rule.

Rules you must follow:
- Judge only the values you are given. You cannot see the reports, and you must not \
assume anything that is not listed.
- Answer "pass" when the values clearly satisfy the rule, "fail" when they clearly do \
not, and "review" when the rule is ambiguous about this case or the values do not \
settle it. Prefer "review" to a guess.
- Do not do arithmetic beyond the comparison the rule states; the values are already \
computed and reliable.
- Give one short sentence of reasoning and a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Rule: The state mix should be plausible for a campaign limited to two states.
Values: il_share = 0.54, az_share = 0.46, other_share = 0.0
Answer:
{"verdict": "pass", "reason": "Both in-scope states carry roughly half the volume and \
nothing else appears.", "confidence": 0.86}

Example 2
Rule: The state mix should be plausible for a campaign limited to two states.
Values: il_share = 0.02, az_share = 0.03, other_share = 0.95
Answer:
{"verdict": "fail", "reason": "Almost all volume sits outside the two states the \
campaign covers.", "confidence": 0.91}

Example 3
Rule: Delivery volume should be in line with the customer's usual order size.
Values: delivered_count = 181224
Answer:
{"verdict": "review", "reason": "No usual order size was supplied, so this value cannot \
be judged.", "confidence": 0.4}
"""

_TEMPLATE: Final = """\
${examples}
Now answer for this rule.

Rule: ${instruction}
Values: ${values}

Answer:"""


JUDGMENT_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="admin_judgment",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=JudgmentResponse,
    )
)
