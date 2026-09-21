"""Which sheet, column, label or report type was meant (Phase 6.21a and 6.21e).

Asked only when four deterministic rungs have already failed. That decides what the
prompt may claim: by the time this runs, exact, squashed, token and alternate matching
have all missed, so the honest prior is that the name is genuinely absent — and the
prompt says so, because a model told "find this" will find something.

The question is as narrow as the compliance locator's, and narrow for the same reason.
The model is **not** asked whether a number is right, whether a report is correct, or
whether a delivery passes. It is asked which label on the shelf is the one the tool
went looking for. Code decides what the answer means, which is ADR-001 and is what
keeps the resulting finding explainable.

**It is shown names and nothing else.** Not a cell value, not a row, not an aggregate —
a list of worksheet names, or column headers, or row labels. That is what makes this
call safe to make on every report in the product (ADR-003), and the tripwire scans it
like every other prompt.

Three answers:

- ``absent`` — none of these is it. Code reports what it would have reported anyway,
  which is a "could not evaluate" finding, or an upload the submitter types for
  themselves, so the common case is unchanged.
- ``found`` — one of them is it under a different name. Code does **not** treat the
  check as clean: it runs the check against that name and attaches a review-severity
  record saying the layout had to be reasoned about, for a person to confirm.
- ``unsure`` — the names do not settle it. Same outcome as ``absent``, and it says so.
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import NameLocation

__all__ = ["NAME_LOCATE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
A validation system is reading a delivery's artifacts. It is looking for one thing — a \
worksheet, a column, a row label, or which kind of report a workbook is — and its own \
matching has already failed to settle it, so it is asking you which of the names it can \
see is the one it wants.

Rules you must follow:
- You are shown a list of names and nothing else. No values, no data, no rows. Do not \
assume anything that is not in the list.
- Answer "found" only when one listed name plainly means the same thing as the name \
asked for. Quote it exactly as it was given to you.
- Answer "absent" when none of them does. This is the expected answer: the system's own \
matching already failed, so absence is the likely truth, not a failure on your part.
- Answer "unsure" when a name might be it and you cannot tell from the names alone. \
Prefer "unsure" to a guess in either direction.
- A near-miss is not a match. A name covering a different population, a different \
step, or a narrower slice of the same thing is "absent" or "unsure", never "found".
- If two listed names both plausibly mean it, answer "unsure" and say which two. \
Choosing between them is not yours to do.
- Do not invent a name. Every name you quote must appear verbatim in the list you were \
given; a name that is not in the list will be rejected.
- Do not decide whether the delivery is correct. You are saying which label is which, \
and a person confirms what you find.
- Give one short sentence of reasoning and a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Looking for: a worksheet called "Attributes" — the sheet listing each delivered field \
with its statistics.
Names available:
- Cover
- Attribute Summary
- Record Counts
Answer:
{"verdict": "found", "name": "Attribute Summary", "reason": "An attribute summary is \
the per-field statistics sheet under a longer name.", "confidence": 0.86}

Example 2
Looking for: a worksheet called "States" — the sheet listing delivered volume by state.
Names available:
- Cover
- Attribute Summary
- Record Counts
Answer:
{"verdict": "absent", "name": "", "reason": "Nothing here breaks the delivery down by \
state or geography.", "confidence": 0.84}

Example 3
Looking for: which report type this workbook is. Its sheets are named "Cover", \
"State Breakdown".
Names available:
- State distribution
- Field distribution
- Number flow
Answer:
{"verdict": "found", "name": "State distribution", "reason": "A state breakdown sheet \
is what a state distribution report carries.", "confidence": 0.81}

Example 4
Looking for: a row label called "Accepts" — the count of records that passed every \
filter.
Names available:
- Input records
- Passed screening
- Passed suppression
- Output records
Answer:
{"verdict": "unsure", "name": "", "reason": "Both \\"Passed screening\\" and \\"Passed \
suppression\\" are single steps, and neither is plainly the final accepted count.", \
"confidence": 0.38}
"""

_TEMPLATE: Final = """\
${examples}
Now answer for this name.

Looking for: ${wanted}
Names available:
${names}

Answer:"""


NAME_LOCATE_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="name_locate",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=NameLocation,
    )
)
