"""Stage 9: a plain-English summary of the findings list.

The model receives the findings only, never the files (``docs/design.md`` "Processing
pipeline", step 9). It writes prose; it does not add, drop, or re-rank findings, because
the summary is a reading aid and the findings list is the record.
"""

from __future__ import annotations

from typing import Final

from vigilai.llm.prompts.registry import Prompt, register
from vigilai.llm.prompts.schemas import SummarizeResponse

__all__ = ["SUMMARIZE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

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
- If the findings list is empty, say that every requirement was traced and matched.
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
Answer:
{"summary": "Every requirement in the specification was traced to the configuration and \
checked against the reports, and all of them matched. No issues were found.", \
"top_issues": []}
"""

_TEMPLATE: Final = """\
{examples}
Now write the summary for these findings.

Findings:
$findings

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
