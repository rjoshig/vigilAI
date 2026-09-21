"""What this delivery calls an attribute, offered to a person (Phase 6.22f).

6.22a made the tool honest: an attribute it cannot locate is a ``review`` record naming
the closest columns, never a high-severity violation. 6.22d gave it somewhere to record
the answer. This is the part that closes the loop between them — the tool proposes the
mapping, a person decides, and the next delivery of that configuration resolves the name
in code and spends no call.

Suggestions come from **two** places, and the order matters because one of them is free:

1. **The record layout** (Phase 6.22b). When the OSL asks for ``AT01``, the DIRT carries
   nothing the ladder can settle, and the uploaded layout declares
   ``debsc_burs_atyrt_at01_1`` — a name that *resembles* ``AT01`` by 6.22a's rules —
   the layout has effectively said what the delivery calls it. That is a proposal code
   makes from a document somebody delivered, at **no model call at all**, and it is why
   the record layout earns its place beyond being one more thing to check.
2. **The ladder's fifth rung** (Phase 6.22d). Where the layout is silent and the model
   was asked and answered, its reading is offered too — bounded by the run's cap, and
   already carrying the review record that says a person should look.

Two rules, and both are ADR-021 restated rather than new:

**Nothing here is in force.** A suggestion is a suggestion until somebody accepts it.
Accepting writes an ``attribute_spellings`` row, and only from then does the fourth rung
resolve the name.

**Who may propose is not who may approve.** Any user may record an observation while
Train AI mode is on; a reviewer or an administrator approves it. A mapping *a person*
proposed activates on approval, because a person vouched for it. A mapping the *model*
read stays in shadow with its review record until a reviewer confirms it — the model
proposing and the model being believed are different things.
"""

from __future__ import annotations

import logging
from typing import Final, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from greenlight_ai.resolve.attributes import near_names
from greenlight_ai.resolve.normalize import squashed

__all__ = [
    "ORIGINS",
    "AttributeSuggestion",
    "from_record_layout",
    "merge",
]

_LOG: Final = logging.getLogger(__name__)

#: Where a suggestion came from, in the order it is trusted. ``record_layout`` first
#: because it is a document the delivery carried and cost nothing to read; ``model``
#: second because it is a reading, which is why it keeps its review record.
ORIGINS: Final[tuple[str, ...]] = ("record_layout", "model")


class AttributeSuggestion(BaseModel):
    """A mapping from an attribute to what this delivery calls it.

    Attributes:
        artifact: Which artifact the spelling belongs to, e.g. ``dirt``. Empty means it
            was not tied to one.
        wanted: The attribute as the OSL asked for it.
        found: What this delivery appears to call it.
        origin: ``record_layout`` or ``model``; see :data:`ORIGINS`.
        confidence: The model's own number for a reading, ``1.0`` for a record layout —
            which is not a claim of certainty but of *provenance*: the layout is a
            document the delivery carried, not a guess about it. A person still decides.
        reason: One line, so the offer can be judged rather than taken on trust.
    """

    model_config = ConfigDict(extra="forbid")

    artifact: str = ""
    wanted: str = ""
    found: str = ""
    origin: str = "model"
    confidence: float = 0.0
    reason: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        """What makes two suggestions the same offer.

        Returns:
            The artifact, and both names squashed — so one run spelling it ``AT01`` and
            another ``at-01`` do not become two things to click.
        """
        return (self.artifact, squashed(self.wanted), squashed(self.found))


def from_record_layout(
    unresolved: Sequence[str],
    layout_names: Sequence[str],
    artifact: str = "dirt",
) -> list[AttributeSuggestion]:
    """Propose what the delivery calls each attribute the tool could not locate.

    Read out of the uploaded record layout, in code, with no model call. The layout is
    the delivered file's own schema: if it declares exactly one field that resembles the
    attribute the OSL asked for, that is the delivery saying what it calls it.

    **Exactly one.** Two resembling names are a tie, and a tie is not an answer — the
    same rule the ladder follows at every rung. Offering a person a guess between two
    would be asking them to do the comparison ADR-001 keeps out of a guess's hands,
    without showing them the workbook.

    Args:
        unresolved: The attributes the checks could not locate, as the OSL asks for them.
        layout_names: Every field the record layout declares.
        artifact: Which artifact the spelling is being proposed for.

    Returns:
        One suggestion per attribute the layout settles, in the order asked. Empty when
        there is no layout, or when it settles none — which is the ordinary state on a
        delivery that carried no layout and changes nothing.
    """
    if not layout_names:
        return []

    out: list[AttributeSuggestion] = []
    for wanted in unresolved:
        near = near_names(wanted, layout_names)
        if len(near) != 1:
            if near:
                _LOG.info(
                    "attribute %r: the record layout offers %d resembling field(s); "
                    "a tie is not an answer",
                    wanted,
                    len(near),
                )
            continue
        found = near[0]
        out.append(
            AttributeSuggestion(
                artifact=artifact,
                wanted=wanted,
                found=found,
                origin="record_layout",
                confidence=1.0,
                reason=(
                    f"The record layout declares {found!r}, the only field it carries "
                    f"that resembles {wanted!r}. Read from the layout in code; no model "
                    "was asked."
                ),
            )
        )
    return out


def merge(
    proposals: Sequence[AttributeSuggestion],
    known: Mapping[str, Sequence[str]] | None = None,
) -> list[AttributeSuggestion]:
    """De-duplicate proposals and drop the ones already recorded.

    Args:
        proposals: Everything proposed this run, in the order it was proposed. The
            first proposal of a mapping wins, which is what puts a record layout's
            reading ahead of the model's — see :data:`ORIGINS`.
        known: Attribute to the spellings the dictionary already holds for it. A
            mapping somebody has already recorded is not an offer; listing it again is
            how a console teaches people to click past it (Phase 6.21b said the same
            about the layout map).

    Returns:
        The offers worth showing, in proposal order.
    """
    recorded = {
        (squashed(attribute), squashed(spelling))
        for attribute, spellings in (known or {}).items()
        for spelling in spellings
    }
    seen: set[tuple[str, str, str]] = set()
    out: list[AttributeSuggestion] = []
    for proposal in proposals:
        if not proposal.wanted.strip() or not proposal.found.strip():
            continue
        if proposal.key in seen:
            continue
        seen.add(proposal.key)
        if (squashed(proposal.wanted), squashed(proposal.found)) in recorded:
            continue
        out.append(proposal)
    return out
