"""Admin check drafting: plain English in, named values and an expression out.

This is the **only** LLM call in the admin flow, and it happens once when a check is
authored (``docs/design.md`` "Configurable checks"). After that the check runs as code
on every request at no token cost. The model proposes; an admin corrects and tests the
proposal against the sample reports before activating it.
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import DraftCheckResponse

__all__ = ["DRAFT_CHECK_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
An administrator describes a cross-report check in plain English. You turn it into two \
things: the named values it needs, and an expression over them.

A named value is a pointer into one report. It has a name used in the expression, the \
report type, the sheet, and a locator. A locator is either a cell address, or a label \
lookup: the row whose label column holds a given text, taking the value from another \
column. Prefer the label lookup, because it survives rows being inserted above it.

Rules you must follow:
- Use only the report types and sheets the administrator mentions or that are listed as \
available. Never invent a report.
- The expression may use the named values, numbers, the comparisons \
<, <=, >, >=, ==, !=, the arithmetic + - * / %, the words and / or, and the functions \
abs, min, max, round. Nothing else: no attribute access, no function you were not given.
- Do not evaluate the expression, and do not say whether a delivery passes. Code runs \
the check against real reports.
- Name each value in lower_snake_case, describing what it is rather than where it sits: \
"billing_count", not "h9".
- Write one sentence of reasoning that a reviewer who sees the failure will understand.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Available report types: billing, counts, dirt
Description: Compare the billing count in the billing report, row "Billing count" in \
the Summary sheet, with the delivered count in the number flow report, cell B8 of the \
Flow sheet. Billing must not be more than delivered.
Answer:
{"named_values": [{"name": "billing_count", "report_type": "billing", \
"sheet": "Summary", "kind": "label", "label": "Billing count", "label_column": 0, \
"value_column": 1, "cell": "", "description": "Records billed to the customer"}, \
{"name": "delivered_count", "report_type": "counts", "sheet": "Flow", "kind": "cell", \
"label": "", "label_column": 0, "value_column": 1, "cell": "B8", \
"description": "Records delivered in the number flow"}], \
"expression": "billing_count <= delivered_count", \
"reasoning": "Billing count must not be more than the records delivered in the number \
flow report.", "severity": "high"}

Example 2
Available report types: counts
Description: Every input record must end up as either an accept or a reject. The \
accepts, rejects and input totals are all in the Flow sheet of the number flow report, \
in rows labelled Accepts, Rejects and Input.
Answer:
{"named_values": [{"name": "accepts_count", "report_type": "counts", "sheet": "Flow", \
"kind": "label", "label": "Accepts", "label_column": 0, "value_column": 3, "cell": "", \
"description": "Accepted records"}, {"name": "rejects_count", "report_type": "counts", \
"sheet": "Flow", "kind": "label", "label": "Rejects", "label_column": 0, \
"value_column": 3, "cell": "", "description": "Rejected records"}, \
{"name": "input_count", "report_type": "counts", "sheet": "Flow", "kind": "label", \
"label": "Input", "label_column": 0, "value_column": 3, "cell": "", \
"description": "Records entering the flow"}], \
"expression": "accepts_count + rejects_count == input_count", \
"reasoning": "Every input record ends as an accept or a reject.", "severity": "high"}
"""

_TEMPLATE: Final = """\
${examples}
Now do the same for this description.

Available report types: ${report_types}
Description: ${description}

Answer:"""


DRAFT_CHECK_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="admin_draft_check",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=DraftCheckResponse,
    )
)
