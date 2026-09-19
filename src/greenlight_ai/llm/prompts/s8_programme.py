"""Stage 8, first step: read the delivery against its programme's rules (ADR-026).

A programme rule is a sentence an administrator wrote, with a strictness. The model
reads the delivery's extracted requirements, configuration description, and report
summaries and names which rules the evidence breaks, quoting the evidence. It does
not grade: code assigns the severity from the rule's strictness, so the model judges
meaning and nothing else (ADR-001).
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import ProgrammeRulesResponse

__all__ = ["PROGRAMME_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
A delivery belongs to a programme, and the programme has rules an administrator wrote \
in plain words. You are shown the rules, each with an id, and then what the delivery \
contains: the requirements extracted from its OSL, a description of its \
configuration, and one-line summaries of its reports.

Name every rule the delivery breaks, quoting the piece of evidence that breaks it. A \
rule the delivery satisfies, or that the evidence does not speak to, is not listed. \
An empty list is a correct answer when nothing is broken.

Rules you must follow:
- Judge meaning only. Do not decide how serious a breach is; the administrator set \
that when writing the rule, and code applies it.
- Do not add up counts, and do not check numbers against each other. Code does every \
comparison. Report only what the words say.
- Quote evidence from what you were shown. Never invent a requirement, a \
configuration element, or a report line.
- Give one breach per rule per piece of evidence, with a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Programme: Account Solicitation
Rules:
- [12] (must) Every prescreen delivery excludes accounts that opted out of firm offers.
- [13] (should) Score bands are named exactly as the OSL names them.
Delivery:
Requirements: geography states CA, TX; score at least 700; exclude opt-out flag = Y.
Configuration: filters on state in [CA, TX]; score >= 700; no filter on opt-out.
Reports: state distribution CA 61%, TX 39%; score bands A, B as in the OSL.
Answer:
{"breaches": [{"rule_id": 12, "evidence": "Configuration: no filter on opt-out", \
"reason": "The programme rule requires opt-out accounts to be excluded and the \
configuration carries no such filter.", "confidence": 0.9}]}

Example 2
Programme: Archives
Rules:
- [4] (advisory) Archive extracts state the as-of date in the OSL.
Delivery:
Requirements: as-of date 2025-12-31; attributes name, balance.
Configuration: snapshot date 2025-12-31; attributes name, balance.
Reports: counts input 1000, delivered 1000.
Answer:
{"breaches": []}
"""

_TEMPLATE: Final = """\
${examples}
Now do the same for this delivery.

Programme: ${programme}
Rules:
${rules}
Delivery:
${delivery}

Answer:"""


PROGRAMME_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="s8_programme",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=ProgrammeRulesResponse,
    )
)
