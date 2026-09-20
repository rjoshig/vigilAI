"""Reading the requirements nothing evidenced, for obligations (Phase 6.11f).

Code works out which requirements no report check reached. That list is where a
compliance error hides: nothing disagreed with it because nothing was compared against
it, and a reviewer reading a short findings list has no reason to look.

The model is given that list, in words, and asked one narrow question: which of these
read like obligations, and why. It does not decide anything. What it points at becomes
a review item for a person, never a graded finding, because there is no evidence behind
it to grade (ADR-001, ADR-034).

It runs in stage 8, with the other model calls, so stage 7 and the re-check path stay
free of them (``docs/design.md`` "Re-check path"). It reads the list stage 7 settled.

It sees requirement text and references only. No report value, no configuration value,
no row (ADR-003).
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import CoverageGapResponse

__all__ = ["COVERAGE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
You are given requirements from a credit-data specification that the validation system \
could not check against any delivered report. Nothing disagreed with them because \
nothing was compared against them.

Your one question: which of these read like an obligation — something a regulator, a \
contract, or a compliance policy requires — rather than an ordinary processing detail?

Rules you must follow:
- Judge only the text in front of you. Do not guess what a requirement means beyond \
what it says, and do not assume a delivery obeyed or broke it: nothing was checked.
- Name a requirement only by the id given to it. Never invent an id.
- Return only the ones that read like obligations. An empty list is the right answer \
when none of them do, and it is a common one.
- Obligations usually concern who may be contacted or solicited, what must be excluded \
or suppressed, consent and opt-out, retention or permissible purpose, and what a \
delivery must be able to evidence afterwards.
- A threshold, a field list, a file count or an ordinary filter is a processing detail, \
not an obligation, unless the text itself ties it to a rule someone must obey.
- Give one short sentence saying which obligation you mean, and a confidence between 0 \
and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Requirements that were not checked:
- R-004 (OSL section 7): Consumers who have opted out of firm offers of credit must be \
excluded from every delivery.
- R-009 (OSL section 11): Return the standard forty-attribute layout.
Answer:
{"gaps": [{"rule_id": "R-004", "reason": "Opt-out from firm offers is a permissible-purpose \
obligation, and nothing in the reports evidences that the exclusion was applied.", \
"confidence": 0.93}]}

Example 2
Requirements that were not checked:
- R-002 (OSL section 3): Sort the output by account number.
- R-005 (OSL section 4): Use the v3 score model.
Answer:
{"gaps": []}
"""

_TEMPLATE: Final = """\
{examples}
Now answer for these requirements.

Requirements that were not checked:
$requirements

Answer:"""


COVERAGE_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="s8_coverage",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("{examples}", _EXAMPLES),
        schema=CoverageGapResponse,
    )
)
