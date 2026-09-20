"""Where a configuration implements a compliance control (Phase 6.15, option A).

Asked only when the deterministic matcher finds nothing. That matters for what the
prompt may claim: by the time this runs, four code tests have already failed to find the
control, so the honest prior is that it is probably absent — and the prompt says so,
because a model told "find this" will find something.

The question is deliberately narrow. The model is **not** asked whether the delivery is
compliant; it is asked where a thing is. Code decides what the answer means, which is
ADR-001 and is what keeps a compliance verdict explainable.

Three answers, and the middle one is the point of the exercise:

- ``absent`` — nothing here implements it. Code raises the high-severity finding it
  would have raised anyway, so the common case is unchanged.
- ``found`` — it is implemented at a path the rule does not name. Code does **not**
  clear the rule: it raises a review-severity finding asking a person to confirm, and
  confirming adds the path to the rule so the next run matches in code.
- ``unsure`` — the configuration does not settle it. Review severity, and it says so.
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import ComplianceLocation

__all__ = ["COMPLIANCE_LOCATE_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
A validation system checks that an ETL configuration implements a required control. Its \
own path matching has already failed to find this control, so it is asking you to read \
the configuration's structure and say where the control is, if it is anywhere.

Rules you must follow:
- You are shown configuration paths and the shape of their contents. You are not shown \
any data, and you must not assume anything that is not listed.
- Answer "found" only when a listed path plainly implements the control described. \
Quote that path exactly as it was given to you.
- Answer "absent" when nothing listed implements it. This is the expected answer: the \
system's own matching already failed, so absence is the likely truth, not a failure on \
your part.
- Answer "unsure" when a path might implement it and you cannot tell from its name and \
shape. Prefer "unsure" to a guess in either direction.
- A near-miss is not a match. A path that handles a different control, or handles this \
one for a different population, is "absent" or "unsure", never "found".
- Do not invent a path. Every path you quote must appear verbatim in the list you \
were given; a path that is not in the list will be rejected.
- Do not decide whether the delivery is compliant. You are saying where something is, \
and a person confirms what you find.
- Give one short sentence of reasoning and a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Control: OFAC suppression — every delivery must screen against the SDN list.
Configuration paths:
- suppressions.sdn_screening (boolean)
- suppressions.deceased (boolean)
- output.format (string)
Answer:
{"verdict": "found", "json_path": "suppressions.sdn_screening", "reason": "SDN \
screening is the OFAC list under the vendor's name for it.", "confidence": 0.88}

Example 2
Control: Opt-out list applied — suppress anyone on the customer's opt-out file.
Configuration paths:
- suppressions.deceased (boolean)
- dedupe.key (list)
- output.format (string)
Answer:
{"verdict": "absent", "json_path": "", "reason": "Nothing here suppresses an opt-out \
or do-not-contact population.", "confidence": 0.82}

Example 3
Control: Opt-out list applied — suppress anyone on the customer's opt-out file.
Configuration paths:
- filters.exclusion_file (string)
- suppressions.deceased (boolean)
Answer:
{"verdict": "unsure", "json_path": "filters.exclusion_file", "reason": "An exclusion \
file may or may not be the opt-out list; its name does not say which population it \
holds.", "confidence": 0.41}
"""

_TEMPLATE: Final = """\
${examples}
Now answer for this control.

Control: ${control}
Configuration paths:
${paths}

Answer:"""


COMPLIANCE_LOCATE_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="compliance_locate",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=ComplianceLocation,
    )
)
