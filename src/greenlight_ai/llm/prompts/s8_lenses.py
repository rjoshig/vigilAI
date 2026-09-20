"""Stage 8's three lenses: the same evidence read from three stances (Phase 6.11e).

Different lenses catch different classes of error. A delivery lead reads a report
asking whether the output matches what was configured; a compliance officer asks which
obligation a discrepancy breaches; the requirements owner asks whether this is what the
specification asked for. One prompt cannot hold all three stances at once, and a
finding one lens waves through another stops on.

**They never see each other.** Each lens is given the finding and its evidence and
nothing else, answers the same schema, and code merges the answers
(:mod:`greenlight_ai.pipeline.s8_verify`). A conversation between them would cost
several times the calls, would converge on whichever answer was stated most
confidently, and would leave a record nobody could replay — and there is nothing for
them to debate anyway, because every comparison was already done by code (ADR-001,
ADR-034).

A lens may lower confidence and may raise a possibility. It may not raise a severity:
the severities code set stand.
"""

from __future__ import annotations

from typing import Final, Mapping

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import LensResponse

__all__ = ["LENSES", "LENS_PROMPTS", "VERSION", "lens_prompt"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

#: The lenses, in the order their opinions are shown.
LENSES: Final[tuple[str, ...]] = ("delivery", "compliance", "requirements")

_SHARED_RULES: Final = """\
Rules you must follow, whichever question you are answering:
- Judge only what the evidence shows. Every number in it was compared by code and is \
reliable. Do not recompute anything, and do not estimate.
- Answer agreed=true when the evidence supports the finding as stated, from your \
point of view.
- Answer agreed=false when it does not, for example when the requirement has been \
misread or the two items are about different things. Disagree when you have a reason, \
not when you are merely unsure: a disagreement does not delete the finding, it sends \
it to a person.
- You may add at most one item to "missed": something this same evidence shows that \
the finding does not mention. Only from the evidence in front of you. Never repeat the \
finding itself, and never invent a value you were not shown.
- Give one short sentence of reasoning and a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_DELIVERY_SYSTEM: Final = """\
You read a credit-data delivery the way the person who has to ship it does. Your \
question is whether the delivery matches what was configured and what was promised: \
did the files that went out do what the configuration says they do, and does the \
output hang together.

You are one of three independent readers of this finding. You cannot see the others \
and they cannot see you. Answer for yourself.

""" + _SHARED_RULES

_COMPLIANCE_SYSTEM: Final = """\
You read a credit-data delivery the way a compliance officer does. Your question is \
which obligation a discrepancy touches: a rule about who may be solicited, what may be \
delivered, what must be excluded or suppressed, and what the delivery must be able to \
evidence afterwards.

You are one of three independent readers of this finding. You cannot see the others \
and they cannot see you. Answer for yourself.

A finding that looks small to someone else may be the one that matters to you. Say so \
plainly, and say which obligation you mean.

""" + _SHARED_RULES

_REQUIREMENTS_SYSTEM: Final = """\
You read a credit-data delivery the way the person who wrote the requirement does. \
Your question is whether the delivery is what the specification asked for: does the \
configuration express the requirement faithfully, and do the reports show it was \
applied.

You are one of three independent readers of this finding. You cannot see the others \
and they cannot see you. Answer for yourself.

You are the reader most likely to spot a requirement that was read too narrowly or too \
widely. Two thresholds that are written differently and mean the same thing are not a \
mismatch.

""" + _SHARED_RULES

_EXAMPLES: Final = """\
Example 1
Finding: value_mismatch — the specification requires a score of at least 755; the \
configuration uses 750.
Evidence: OSL section 4 says "score | at least | 755". Configuration rules.score_v3 has \
min 750. The delivered minimum score is 750.
Answer:
{"agreed": true, "reason": "The specification and the configuration state different \
thresholds and the delivery matches the lower one.", "confidence": 0.97, "missed": []}

Example 2
Finding: value_mismatch — the specification allows utilization below 60 percent; the \
configuration uses 0.60.
Evidence: OSL section 4 says "revolving utilization | below | 60%". Configuration \
rules.util has max 0.60 with operator "<".
Answer:
{"agreed": false, "reason": "60 percent and 0.60 are the same threshold with the same \
operator, so there is no mismatch.", "confidence": 0.9, "missed": []}

Example 3
Finding: rule_missing_in_config — the specification requires a bankruptcy exclusion and \
no configuration element implements it.
Evidence: OSL section 7 says "Exclude any consumer with a bankruptcy filed within the \
last 24 months." Configuration suppressions contains ofac and deceased only.
Answer:
{"agreed": true, "reason": "No configuration element addresses bankruptcy.", \
"confidence": 0.92, "missed": [{"title": "The suppression list may be incomplete for \
this programme", "reason": "Only two suppressions are configured and the specification \
names a third.", "confidence": 0.6}]}
"""

_TEMPLATE: Final = """\
{examples}
Now answer for this finding.

Finding: $finding
Evidence: $evidence

Answer:"""


def _build(name: str, system: str) -> Prompt:
    """Register one lens.

    Args:
        name: The lens name, which becomes its stage (``"s8_lens_delivery"``) and so
            its own cache key: each lens's answer is cached separately.
        system: Its system prompt.

    Returns:
        The registered prompt.
    """
    return register(
        Prompt(
            stage=f"s8_lens_{name}",
            version=VERSION,
            system=system,
            template=_TEMPLATE.replace("{examples}", _EXAMPLES),
            schema=LensResponse,
        )
    )


#: Each lens by name.
LENS_PROMPTS: Final[Mapping[str, Prompt]] = {
    "delivery": _build("delivery", _DELIVERY_SYSTEM),
    "compliance": _build("compliance", _COMPLIANCE_SYSTEM),
    "requirements": _build("requirements", _REQUIREMENTS_SYSTEM),
}

#: How each lens is described to a reviewer, beside its opinion.
LENS_LABEL: Final[Mapping[str, str]] = {
    "delivery": "Delivery",
    "compliance": "Compliance",
    "requirements": "Requirements owner",
}


def lens_prompt(name: str) -> Prompt:
    """Look up a lens by name.

    Args:
        name: The lens name.

    Returns:
        Its prompt.

    Raises:
        KeyError: When the name is not a lens, which is a configuration error the
            caller reports rather than silently skipping a reader.
    """
    return LENS_PROMPTS[name]
