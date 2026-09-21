"""The deterministic rungs: four ways to recognise a name, tried in order.

The package docstring says why. This module says how, and the two rules that make the
result defensible:

**A rung that ties is a rung that failed.** If two candidates match equally well the
ladder does not pick one — picking would be a comparison nobody could reproduce, and
the tie is exactly the case a person or the model should settle. The ladder falls
through with every candidate still on the table.

**A later rung never overrules an earlier one.** The rungs are ordered by how much they
assume, and the first unambiguous answer wins. That is what guarantees the sentence in
the package docstring: nothing that matched before this package existed stops matching
now, because rung 1 *is* what every caller did before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Sequence

from greenlight_ai.resolve.normalize import squashed, tokens

__all__ = [
    "DETERMINISTIC_RUNGS",
    "MAX_EXTRA_TOKENS",
    "RUNGS",
    "Resolution",
    "Rung",
    "resolve",
]

#: How a name was recognised, from the least assuming to the most.
Rung = Literal["exact", "squashed", "tokens", "alternate", "model"]

#: Every rung, in ladder order.
RUNGS: Final[tuple[Rung, ...]] = ("exact", "squashed", "tokens", "alternate", "model")

#: The rungs this module implements. The fifth is a model call and lives in
#: :mod:`greenlight_ai.resolve.locate`.
DETERMINISTIC_RUNGS: Final[tuple[Rung, ...]] = RUNGS[:-1]

#: How many words a candidate may carry beyond the ones asked for and still be that
#: name. ``Attributes`` reaches ``Attribute Summary`` (one extra) and ``Attribute
#: Summary By Segment`` (three) does not: past a couple of words it is a different
#: sheet, not the same sheet spelled longer.
MAX_EXTRA_TOKENS: Final[int] = 2

#: What the deterministic rungs claim for themselves. They are not guesses: each one is
#: a rule a person can recompute by hand, which is the property that lets code act on
#: the answer without asking anybody.
_CERTAIN: Final[float] = 1.0


@dataclass(frozen=True, slots=True)
class Resolution:
    """Which candidate a wanted name resolved to, and how.

    Attributes:
        wanted: The name as the tool asked for it.
        value: The candidate it resolved to, spelled as the artifact spells it. This is
            what a caller must use to read the artifact.
        rung: Which rung reached it.
        confidence: ``1.0`` for the deterministic rungs, the model's own number for the
            fifth. Code applies the floor; this only reports.
        reason: One line a reviewer can read, naming what was asked for and what was
            found.
    """

    wanted: str
    value: str
    rung: Rung
    confidence: float = _CERTAIN
    reason: str = ""

    @property
    def exact(self) -> bool:
        """Whether this is the answer the tool would have found before Phase 6.21."""
        return self.rung == "exact"

    @property
    def reasoned(self) -> bool:
        """Whether the model reached this, and so a person must confirm it.

        Returns:
            True only for the model rung. A ``True`` here is what turns a finding into
            a review-severity record that also says the layout was reasoned about.
        """
        return self.rung == "model"


def _unique(matches: Sequence[str]) -> str | None:
    """The one candidate in ``matches``, or ``None`` when there is not exactly one.

    Args:
        matches: Candidates a rung accepted, in candidate order.

    Returns:
        The single match, or ``None`` when the rung found none or tied. Candidates that
        are the same string are one match, because a workbook listing the same sheet
        name twice is not an ambiguity anybody can act on.
    """
    distinct = list(dict.fromkeys(matches))
    return distinct[0] if len(distinct) == 1 else None


def _covers(wanted: Sequence[str], actual: Sequence[str]) -> bool:
    """Whether ``wanted`` appears in ``actual`` in order, not necessarily adjacently.

    A subsequence rather than a contiguous run, for the same reason
    ``compliance_match`` uses one: the thing being tolerated is an extra word between
    two the caller named. ``Records out`` should reach ``Records taken out``.

    Args:
        wanted: The asked-for name's tokens.
        actual: The candidate's tokens.

    Returns:
        True when every wanted token is found in order.
    """
    if not wanted:
        return False
    index = 0
    for token in actual:
        if token == wanted[index]:
            index += 1
            if index == len(wanted):
                return True
    return False


def _token_match(wanted: str, candidate: str) -> bool:
    """Whether two names are the same words, allowing a couple of extra ones.

    Args:
        wanted: The asked-for name.
        candidate: A candidate name.

    Returns:
        True when the candidate's tokens are the wanted tokens as a set, or contain
        them in order with at most :data:`MAX_EXTRA_TOKENS` words besides. A candidate
        with *fewer* words than asked for never matches here: ``Attribute`` reaching
        ``Attributes`` is rung 2's job, and ``Flow`` must not reach ``Flow`` in a
        workbook that also has ``Flow Detail`` by dropping a word.
    """
    asked = tokens(wanted)
    offered = tokens(candidate)
    if not asked or not offered:
        return False
    if set(asked) == set(offered):
        return True
    if len(offered) < len(asked) or len(offered) - len(asked) > MAX_EXTRA_TOKENS:
        return False
    return _covers(asked, offered)


def resolve(
    wanted: str,
    candidates: Sequence[str],
    alternates: Sequence[str] = (),
) -> Resolution | None:
    """Work out which candidate a wanted name refers to, in code.

    Args:
        wanted: The name the tool is looking for.
        candidates: The names the artifact actually carries, spelled as it spells them.
        alternates: Other names that also mean this one, written by an administrator.
            Reached only after the first three rungs fail, because an alternate is a
            different word rather than a different spelling and is therefore a stronger
            claim than any amount of normalising.

    Returns:
        The resolution, or ``None`` when no rung found exactly one candidate. ``None``
        is not "absent": it is "code cannot say", and the caller may offer the same
        candidates to :func:`greenlight_ai.resolve.locate.locate`.
    """
    asked = wanted.strip()
    if not asked or not candidates:
        return None

    # Rung 1, in three steps, because "exact" has a tie of its own. A counts report
    # that carries a waterfall step called `input` *and* a total row called `Input`
    # offers two case-insensitive matches for either name, and they are different rows.
    # Spelling decides it: whichever is written the way the caller wrote it is the one
    # meant. Only when spelling does not decide does this fall back to the first
    # candidate, which is what every caller did before Phase 6.21 and is the behaviour
    # this rung exists to preserve.
    verbatim = _unique([c for c in candidates if c.strip() == asked])
    if verbatim is not None:
        return Resolution(asked, verbatim, "exact", _CERTAIN, f"{verbatim!r} is {asked!r}.")

    lowered = asked.lower()
    insensitive = [c for c in candidates if c.strip().lower() == lowered]
    hit = _unique(insensitive) or (insensitive[0] if insensitive else None)
    if hit is not None:
        return Resolution(asked, hit, "exact", _CERTAIN, f"{hit!r} is {asked!r}.")

    squashed_wanted = squashed(asked)
    if squashed_wanted:
        hit = _unique([c for c in candidates if squashed(c) == squashed_wanted])
        if hit is not None:
            return Resolution(
                asked,
                hit,
                "squashed",
                _CERTAIN,
                f"{hit!r} is {asked!r} spelled with different separators.",
            )

    hit = _unique([c for c in candidates if _token_match(asked, c)])
    if hit is not None:
        return Resolution(
            asked,
            hit,
            "tokens",
            _CERTAIN,
            f"{hit!r} carries the same words as {asked!r}.",
        )

    for alternate in alternates:
        spelled = alternate.strip()
        if not spelled:
            continue
        squashed_alternate = squashed(spelled)
        hit = _unique(
            [
                c
                for c in candidates
                if c.strip().lower() == spelled.lower()
                or (squashed_alternate and squashed(c) == squashed_alternate)
            ]
        )
        if hit is not None:
            return Resolution(
                asked,
                hit,
                "alternate",
                _CERTAIN,
                f"{hit!r} is what this delivery calls {asked!r}, per {spelled!r}.",
            )

    return None
