"""Which delivery programme a set of artifacts reads like (Phase 6.18f).

Asked only where the keyword check has already failed to find any of the declared
programme's words. That matters for what the prompt may claim: by the time this runs,
a deterministic match that tolerates plurals, hyphens and reordered phrases has found
nothing, so **either the customer uses vocabulary nobody has taught the tool, or the
delivery really is a different programme** — and the first is more common than the
second. The prompt says so, because a model told "work out which one" will pick one.

The question is deliberately narrow. The model is **not** asked whether the submitter
was right; it is asked what the documents sound like, and code compares that with what
was declared (ADR-001). A design where the model answers "the declaration is wrong" is
out of scope however it is dressed, because that is a comparison.

Two answers, and the second is the useful one as often as the first:

- ``reads_like`` with a programme code — the documents plainly describe one of the
  listed programmes. Code compares it with the declaration: agreeing **silences the
  keyword finding** and offers the quoted phrases as keywords, so the next run matches
  in code; disagreeing reports at high severity, which is what the check is for.
- ``unclear`` — the documents do not settle it. Code reports at review severity, which
  is the honest answer and is what the keyword check would have said alone.

The phrases matter as much as the verdict. They are what an administrator adds to the
programme's word list, and adding them is what stops the model being asked again.
"""

from __future__ import annotations

from typing import Final

from greenlight_ai.llm.prompts.registry import Prompt, register
from greenlight_ai.llm.prompts.schemas import ProgrammeReading

__all__ = ["PROGRAMME_READING_PROMPT", "VERSION"]

#: Bump on any wording change: the version is part of the cache key (ADR-005).
VERSION: Final[str] = "1"

_SYSTEM: Final = """\
A validation system checks that a delivery is the kind of delivery its submitter says \
it is. Its own keyword matching has already failed to find any of the declared \
programme's words, so it is asking you to read the documents and say which of the \
listed programmes they sound like, if any.

Rules you must follow:
- You are shown a programme list and extracts from the delivery's own documents. Use \
only those; do not assume anything that is not shown.
- Answer "reads_like" with a programme code **only when the documents plainly describe \
that programme's work**. Quote the words that say so.
- Answer "unclear" when the documents do not settle it. **This is a perfectly good \
answer and often the right one**: the system's own matching already failed, which \
usually means the customer writes about this work in words nobody has taught it, not \
that the delivery is something else. Prefer "unclear" to a guess.
- Use only a programme code from the list you were given. A code that is not in the \
list will be rejected.
- Quote at most five phrases, verbatim from the documents. They are shown to a person \
and offered as new keywords, so a phrase you invent wastes somebody's time.
- Do not say whether the submitter was right or wrong. You are saying what the \
documents sound like; the system compares that with what was declared.
- Do not describe or repeat any personal data, and do not quote a phrase that contains \
a person's name, address or account number. The phrases are about the kind of work, \
never about who is in the file.
- Give one short sentence of reasoning and a confidence between 0 and 1.
- Answer with a single JSON object and nothing else. No prose, no code fence.
"""

_EXAMPLES: Final = """\
Example 1
Programmes:
- AS: Account Solicitation — prescreen and invitation-to-apply campaigns.
- AM: Account Monitoring — ongoing review of an existing portfolio.
Documents say:
A promotional acquisition mailing for consumers who do not hold a card. Suppress \
existing accounts. Scored above the cut, delivered to the mail house monthly.
Answer:
{"programme_code": "AS", "verdict": "reads_like", "phrases": ["promotional acquisition \
mailing", "consumers who do not hold a card", "delivered to the mail house"], "reason": \
"An outbound campaign to non-customers, with current customers suppressed.", \
"confidence": 0.86}

Example 2
Programmes:
- AS: Account Solicitation — prescreen and invitation-to-apply campaigns.
- ARCHIVE: Archives — historical or archival extracts.
Documents say:
Monthly file. Counts by state and band. Delivered on the third working day.
Answer:
{"programme_code": "", "verdict": "unclear", "phrases": [], "reason": "The extract \
describes a delivery schedule and a layout, and says nothing about what the work is \
for.", "confidence": 0.71}

Example 3
Programmes:
- AM: Account Monitoring — ongoing review of an existing portfolio.
- ARCHIVE: Archives — historical or archival extracts.
Documents say:
A back-file pull of closed trades from prior years, frozen as at each period end, for \
the retention window.
Answer:
{"programme_code": "ARCHIVE", "verdict": "reads_like", "phrases": ["back-file pull of \
closed trades from prior years", "for the retention window"], "reason": "A historical \
extract of closed business, not a review of a live portfolio.", "confidence": 0.9}
"""

_TEMPLATE: Final = """\
${examples}
Now answer for this delivery.

Programmes:
${programmes}

Documents say:
${extracts}

Answer:"""


PROGRAMME_READING_PROMPT: Final[Prompt] = register(
    Prompt(
        stage="programme_reading",
        version=VERSION,
        system=_SYSTEM,
        template=_TEMPLATE.replace("${examples}", _EXAMPLES),
        schema=ProgrammeReading,
    )
)
