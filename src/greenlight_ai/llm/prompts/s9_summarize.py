"""Stage 9: a plain-English summary of the findings list.

The model receives the findings only, never the files (``docs/design.md`` "Processing
pipeline", step 9). It writes prose; it does not add, drop, or re-rank findings, because
the summary is a reading aid and the findings list is the record.
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import SummarizeResponse

__all__ = ["SUMMARIZE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "2"

_SYSTEM: Final = """\
You write the summary shown at the top of a quality-control report for a credit-data \
delivery. You are given the list of findings a validation system produced.

Rules you must follow:
- Summarise only the findings given. Never introduce an issue that is not in the list, \
and never claim something passed unless the list says so.
- Do not recompute or re-rank anything. The severities are already decided.
- Write one short paragraph, at most five sentences, in plain English for a reviewer \
who has not seen the files. Name the specific values that differ where the findings \
give them.
- List the most serious issues separately in top_issues, one short line each, most \
serious first, at most five.
- You are also given the run's coverage: how many requirements a report check actually \
compared, and how many were left unchecked or can only be verified by hand. These are \
counts code produced. Never restate them as more than they are, and never treat an \
unchecked requirement as one that passed.
- If the findings list is empty and nothing was left unchecked, say that every \
requirement was traced and matched. If the findings list is empty but requirements were \
left unchecked, say that no disagreement was found and name how many requirements \
nothing in the reports evidenced. An empty findings list is not a clean delivery when \
part of it was never examined.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Findings:
- high | value_mismatch | Score threshold is 750 in the configuration; the specification \
requires 755.
- high | report_violates_rule | The state distribution contains TX and NV; only IL and AZ \
are in scope.
- low | profile_anomaly | Null rate for MORT_BAL is 18.2% against a prior median of 4.1%.
Answer:
{"summary": "Two serious problems need attention before this delivery is accepted. The \
configuration accepts scores from 750 where the specification requires 755, so records \
below the agreed threshold were delivered. The state distribution also contains TX and \
NV although only IL and AZ are in scope. One minor anomaly was noted: the null rate for \
MORT_BAL is far above its usual level.", "top_issues": ["Score threshold 750 in the \
configuration against 755 required", "TX and NV present although only IL and AZ are in \
scope"]}

Example 2
Findings:
(none)
Coverage: 14 of 14 requirements were checked against a report; 0 were left unchecked and \
0 need checking by hand.
Answer:
{"summary": "Every requirement in the specification was traced to the configuration and \
checked against the reports, and all of them matched. No issues were found.", \
"top_issues": []}

Example 3
Findings:
(none)
Coverage: 9 of 14 requirements were checked against a report; 3 were left unchecked and \
2 need checking by hand.
Answer:
{"summary": "No disagreement was found between the specification, the configuration and \
the reports. This is not a clean bill of health: of fourteen requirements, nine were \
compared against a report, three were traced to the configuration but evidenced by no \
report, and two can only be verified by reading. Those five need a person before this \
delivery is accepted.", "top_issues": ["Five requirements were not evidenced by any \
report"]}
"""

_TEMPLATE: Final = """\
{examples}
Now write the summary for these findings.

Findings:
$findings

Coverage: $coverage

Answer:"""


SUMMARIZE_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="s9_summarize",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("{examples}", _EXAMPLES),
        schema=SummarizeResponse,
    )
)
