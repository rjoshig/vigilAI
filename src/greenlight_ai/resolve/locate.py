"""The ladder's fifth rung: ask the model which name was meant (Phase 6.21a).

Reached only where :func:`greenlight_ai.resolve.ladder.resolve` returned ``None``. The
discipline is the one Phase 6.15 established for compliance controls and 6.17a repeated
for programmes, and it is restated here rather than assumed, because it is the whole
reason a model call is allowed to touch a validation result at all:

1. **Names, never values.** The model is shown a list of worksheet names, column
   headers or row labels. It is never shown a cell, a row or an aggregate (ADR-003).
2. **Code checks the answer.** The name it quotes must be one that was offered. A name
   nobody offered is a hallucination, and believing one would be the comparison ADR-001
   keeps out of the model's hands.
3. **A floor applies.** Below :data:`CONFIDENCE_FLOOR` the model was guessing, and a
   guess has told us nothing the four deterministic rungs had not already.
4. **It is never a pass.** What comes back is a :class:`~greenlight_ai.resolve.ladder.
   Resolution` whose ``reasoned`` property is ``True``, and every caller turns that into
   a review-severity record a person confirms.

A run with no client, or one whose token budget is spent, gets ``None`` — the
deterministic answer, which is what it would have had anyway. Degrading is never a
failure here (``s6_reverse._may_locate`` is the precedent).
"""

from __future__ import annotations

import logging
from typing import Final, Sequence

from greenlight_ai.llm.client import LLMClient, LLMError
from greenlight_ai.llm.examples import LibraryExample
from greenlight_ai.llm.prompts.name_locate import NAME_LOCATE_PROMPT
from greenlight_ai.llm.prompts.schemas import NameLocation
from greenlight_ai.resolve.ladder import Resolution
from greenlight_ai.resolve.normalize import squashed

__all__ = ["CONFIDENCE_FLOOR", "MAX_NAMES", "locate"]

_LOG: Final = logging.getLogger(__name__)

#: Below this the model's own answer is treated as "unsure". Matched to the compliance
#: locator's floor deliberately: the two calls carry the same kind of risk and a second
#: number to tune would be a second number to get wrong.
CONFIDENCE_FLOOR: Final[float] = 0.6

#: How many names the model is shown. A workbook is not a search space, and a prompt
#: that is mostly a list stops being a prompt.
MAX_NAMES: Final[int] = 80


def locate(
    client: LLMClient | None,
    wanted: str,
    description: str,
    candidates: Sequence[str],
    *,
    preamble: str = "",
    examples: Sequence[LibraryExample] = (),
) -> Resolution | None:
    """Ask which of ``candidates`` is ``wanted``, and believe the answer only if it holds.

    Args:
        client: The adapter, or ``None`` when this run may not spend a call. ``None``
            returns ``None`` rather than raising: the deterministic answer stands.
        wanted: The name the tool went looking for.
        description: One line saying what kind of thing it is and what it is for, e.g.
            ``'a worksheet called "Attributes" — the sheet listing each delivered field
            with its statistics'``. The model reads names only, so this sentence is the
            only account it gets of what the name means.
        candidates: The names the artifact carries, spelled as it spells them.
        preamble: The run's assembled context block, so a programme's standing
            instructions reach this call like any other (``pipeline/guidance.py``).
        examples: Library examples for this stage, rendered with the prompt.

    Returns:
        A resolution on the model rung, or ``None`` when the call could not be made,
        could not be parsed, or could not be believed — an answer that was not
        ``found``, a name nobody offered, or one below :data:`CONFIDENCE_FLOOR`.
    """
    asked = wanted.strip()
    offered = [c for c in dict.fromkeys(candidates) if c.strip()][:MAX_NAMES]
    if client is None or not asked or not offered:
        return None

    listed = "\n".join(f"- {name}" for name in offered)
    try:
        result = client.complete(
            NAME_LOCATE_PROMPT.system,
            preamble
            + NAME_LOCATE_PROMPT.render_with_examples(
                tuple(examples),
                wanted=description or asked,
                names=listed,
            ),
            NameLocation,
            stage="name_locate",
            prompt_version=NAME_LOCATE_PROMPT.version,
        )
        answer = result.parsed(NameLocation)
    except LLMError as exc:
        _LOG.info("name %r: locator did not answer (%s)", asked, type(exc).__name__)
        return None

    if answer.verdict != "found":
        _LOG.info("name %r: locator answered %s", asked, answer.verdict)
        return None

    # The model was told to quote a name from the list. Code checks that it did.
    # Matched on the squashed form rather than verbatim so a reply that tidied the
    # spacing is still checked against the list rather than thrown away — the test is
    # still "was this one of the names offered", which is the property that matters.
    quoted = squashed(answer.name)
    chosen = next((name for name in offered if squashed(name) == quoted), None)
    if chosen is None:
        _LOG.info("name %r: locator quoted %r, which was not offered", asked, answer.name)
        return None

    if answer.confidence < CONFIDENCE_FLOOR:
        _LOG.info(
            "name %r: locator chose %r below the floor (%.2f)",
            asked,
            chosen,
            answer.confidence,
        )
        return None

    reason = answer.reason.strip() or f"{chosen!r} was read as {asked!r}."
    return Resolution(asked, chosen, "model", answer.confidence, reason)
