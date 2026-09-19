"""Stage 8: a second opinion on one high-severity finding.

A second opinion is requested only for high-severity findings, which keeps the call
volume down (``docs/design.md`` "LLM cost controls"). Disagreement does not delete the
finding: it is kept and downgraded to Review, so the model can reduce false positives
without being able to hide a real problem.
"""

from __future__ import annotations

from typing import Final

from vigilai.llm.prompts.registry import Prompt, register
from vigilai.llm.prompts.schemas import VerifyResponse

__all__ = ["VERIFY_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
A validation system has raised a finding about a credit-data delivery. You are the \
second opinion. Say whether the finding is justified by the evidence shown.

Rules you must follow:
- Judge only what the evidence supports. The numbers have already been compared by \
code and are reliable; do not recompute them.
- Answer agreed=true when the evidence supports the finding as stated.
- Answer agreed=false when the evidence does not support it, for example when the \
requirement has been misread or the two items are about different things.
- A disagreement does not delete the finding; it marks it for closer human review. So \
disagree when you have a reason, not when you are merely unsure.
- Give one short sentence of reasoning and a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Finding: value_mismatch — the specification requires a score of at least 755; the \
configuration uses 750.
Evidence: OSL section 4 says "score | at least | 755". Configuration rules.score_v3 has \
min 750. The delivered minimum score is 750.
Answer:
{"agreed": true, "reason": "The specification and the configuration state different \
thresholds and the delivery matches the lower one.", "confidence": 0.97}

Example 2
Finding: rule_missing_in_config — the specification requires a bankruptcy exclusion and \
no configuration element implements it.
Evidence: OSL section 7 says "Exclude any consumer with a bankruptcy filed within the \
last 24 months." Configuration suppressions contains ofac and deceased only.
Answer:
{"agreed": true, "reason": "No configuration element addresses bankruptcy.", \
"confidence": 0.92}

Example 3
Finding: value_mismatch — the specification allows utilization below 60 percent; the \
configuration uses 0.60.
Evidence: OSL section 4 says "revolving utilization | below | 60%". Configuration \
rules.util has max 0.60 with operator "<".
Answer:
{"agreed": false, "reason": "60 percent and 0.60 are the same threshold with the same \
operator, so there is no mismatch.", "confidence": 0.9}
"""

_TEMPLATE: Final = """\
{examples}
Now answer for this finding.

Finding: $finding
Evidence: $evidence

Answer:"""


VERIFY_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="s8_verify",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("{examples}", _EXAMPLES),
        schema=VerifyResponse,
    )
)
