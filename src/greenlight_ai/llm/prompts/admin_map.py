"""The mapping interview: one OSL section in, requirement links out (Phase 6.10).

An administrator presses Map once per scope. For each OSL section the model reads
the section, the list of configuration blocks, and the list of report cells (labels
only, never values), and proposes which block implements each requirement and which
cells evidence it, asking a question when it cannot place one. The model proposes
and never compares (ADR-001); a person confirms; code compiles (ADR-033).
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import MappingProposal

__all__ = ["MAP_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
You read one section of an Order Specification Letter (OSL), a list of the blocks in \
the ETL configuration that built the delivery, and a list of the cells in the delivery's \
reports. For each requirement the section states, you say which configuration block \
implements it and which report cells evidence it, so an administrator can confirm the \
link once and code can check it on every delivery.

Rules you must follow:
- Report only requirements the section states. Do not invent a requirement, a \
configuration path, or a report cell: use only the paths and cells listed.
- Do not compare values, do arithmetic, or judge whether the delivery is correct. \
Another system does that. Your job is to say where a requirement answers to.
- When you cannot place a requirement, leave config_path null or report_cells empty and \
ask one short question in the question field. A guess is worse than a question.
- key is a short lower_snake_case name for the requirement, stable across deliveries.
- comparison is "equals" when the first report cell should equal the configuration \
value, "reconciles" when they should agree within a tolerance, or "" when there is \
nothing for code to check.
- Suggest a compliance rule only when the requirement is one every delivery must \
configure regardless of the OSL, naming the configuration path it must contain.
- Give a confidence between 0 and 1 for how sure you are of the link.
- Answer with a single JSON object and nothing else. No prose, no code fence.

The answer has exactly this shape and no other keys anywhere:
{"requirements": [{"key": str, "requirement_text": str, "config_path": str or null, \
"report_cells": [{"report_key": str, "sheet": str, "label": str, "cell": str}], \
"validate": str, "comparison": "" or "equals" or "reconciles", "confidence": number, \
"question": str or null, "compliance_suggestion": {"name": str, \
"json_path_contains": str, "reasoning": str} or null}]}
"""

_EXAMPLES: Final = """\
Example 1
Section:
3 Geography
Include only consumers whose current address is in Illinois or Arizona.
Configuration blocks:
- filters[0] (filters): {"field": "ST", "op": "in", "value": ["IL", "AZ"]}
- rules.score_v3 (rules): {"field": "SCORE_V3", "min": 755, "op": ">="}
Report cells:
- state_distribution States!State (A1)
- state_distribution States!Count (B1)
- counts Flow!Accepts (D8)
Answer:
{"requirements": [{"key": "geography", "requirement_text": "Include only consumers \
whose current address is in Illinois or Arizona.", "config_path": "filters[0]", \
"report_cells": [{"report_key": "state_distribution", "sheet": "States", \
"label": "State", "cell": ""}], "validate": "Every state in the distribution is one of \
the allowed states.", "comparison": "", "confidence": 0.93, "question": null, \
"compliance_suggestion": null}]}

Example 2
Section:
7 Exclusions
Exclude any consumer on the OFAC list. Exclude any consumer recorded as deceased.
Configuration blocks:
- suppressions.deceased (suppressions): true
- output (output): {"fields": ["SCORE_V3", "AGE"]}
Report cells:
- counts Flow!exclusions (A6)
- counts Flow!Accepts (D8)
Answer:
{"requirements": [{"key": "ofac_excluded", "requirement_text": "Exclude any consumer \
on the OFAC list.", "config_path": null, "report_cells": [{"report_key": "counts", \
"sheet": "Flow", "label": "exclusions", "cell": ""}], "validate": "OFAC hits are \
suppressed and counted in the exclusions step.", "comparison": "", "confidence": 0.6, \
"question": "No configuration block mentions OFAC. Is OFAC suppression set elsewhere, or \
is it missing from this configuration?", "compliance_suggestion": {"name": "OFAC \
suppression", "json_path_contains": "suppressions.ofac", "reasoning": "Every delivery \
must suppress OFAC hits."}}, {"key": "deceased_excluded", "requirement_text": "Exclude \
any consumer recorded as deceased.", "config_path": "suppressions.deceased", \
"report_cells": [{"report_key": "counts", "sheet": "Flow", "label": "exclusions", \
"cell": ""}], "validate": "The deceased flag is switched on and the exclusions step \
removes records.", "comparison": "", "confidence": 0.9, "question": null, \
"compliance_suggestion": null}]}
"""

_TEMPLATE: Final = """\
${examples}
Now do the same for this section.

Section:
${section}
Configuration blocks:
${blocks}
Report cells:
${cells}

Answer:"""


MAP_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="admin_map_requirement",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=MappingProposal,
    )
)
