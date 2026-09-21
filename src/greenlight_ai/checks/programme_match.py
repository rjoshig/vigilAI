"""Whether a delivery's own words name a programme (Phase 6.17a).

The programme classification check is a grep: it looks for a programme's keywords in
the OSL, the configuration and the report headers, and reports a mismatch when none of
the declared programme's words appear. `docs/phase-6.17.md` measured what that costs.

Seventeen deliveries, every one genuinely the programme it declared, worded the way
another customer might word it: eleven raised a review item and **five fired at high
severity**. Two defects, and they compounded.

1. **A phrase keyword needed exact adjacency and exact plurality.** ``existing
   accounts`` did not find ``existing account``; ``invitation to apply`` did not find
   ``invitation-to-apply``; ``portfolio review`` did not find *ongoing review of the
   portfolio*. Single-word keywords survived inflection for free because a substring
   test catches ``archives`` for ``archive`` — phrases had no such luck.
2. **Two shipped keywords carried no programme meaning.** Severity rose to high only
   when *another* programme cleared a two-hit floor, and ``snapshot`` and ``historical``
   are ordinary data-delivery vocabulary that any programme's specification contains.
   Archives cleared the floor by accident.

This module widens the match deterministically, in the shape
`compliance_match.py` established. Three ways to find a keyword, and it counts if
**any** of them does, so nothing that matched before stops matching:

1. **Normalised substring.** What the check did before, with punctuation and hyphens
   folded to spaces. This is listed first because it is what preserves every match the
   old behaviour made, inflections included: ``prescreen`` still finds ``prescreened``.
2. **Adjacent tokens, singular or plural.** The keyword's words in order and next to
   each other, compared after a light singular fold — so ``existing accounts`` finds
   ``existing account``, and ``invitation to apply`` finds ``invitation-to-apply`` once
   the hyphens are spaces.
3. **The same words close together, in any order.** A multi-word keyword whose words
   all appear within a short window — so ``portfolio review`` finds *ongoing review of
   the portfolio*. Only for multi-word keywords: a single word is already covered by
   rule 1, and a window around one word would mean nothing.

What it deliberately does **not** do is guess at vocabulary. A customer who calls a
prescreen a *promotional acquisition campaign* shares no word with any spelling of
``prescreen``, and no amount of normalising reaches that. Widening the match narrows
the gap between *absent* and *spelled differently* without pretending to close it —
closing it is what an administrator's added keyword does, and what the model is for in
[`phase-6.18.md`](../../../docs/phase-6.18.md) 6.18f.
"""

from __future__ import annotations

import re
from typing import Final, Iterable, Mapping, Sequence

__all__ = [
    "WINDOW",
    "discriminating",
    "fold",
    "found",
    "hits",
    "normalized_key",
    "tokens",
]

#: Anything that is not a letter or a digit separates words. Hyphens, underscores,
#: slashes and punctuation all become the same thing, so ``invitation-to-apply`` and
#: ``invitation to apply`` normalise alike.
_NOISE: Final = re.compile(r"[^a-z0-9]+")

#: How far apart a multi-word keyword's words may sit and still count as that keyword.
#: Six tokens covers the connectives English puts between them — *ongoing review **of
#: the** portfolio* — without reaching into the next sentence's subject.
WINDOW: Final[int] = 6

#: Below this length a trailing ``s`` is more likely to be part of the word than a
#: plural, so the fold leaves it alone.
_MIN_FOLD: Final[int] = 4


def fold(token: str) -> str:
    """Reduce one word to a form that compares across singular and plural.

    Deliberately not a stemmer. A stemmer would also fold tense and derivation, which
    this check does not need and which would make a false match harder to explain to
    the person reading the finding.

    Args:
        token: One normalised word.

    Returns:
        The word with a plural ending removed, or unchanged when removing one would be
        a guess. ``accounts`` folds to ``account``; ``across`` and ``is`` do not fold.
    """
    if len(token) >= _MIN_FOLD + 1 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) >= _MIN_FOLD and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(value: str) -> tuple[str, ...]:
    """Split text into normalised, folded words.

    Args:
        value: Any text — a document's prose, a configuration path, a column header.

    Returns:
        The words, lowercased, stripped of punctuation, and singular-folded.
    """
    return tuple(fold(word) for word in _NOISE.sub(" ", value.lower()).split() if word)


def _normalized(value: str) -> str:
    """Text with punctuation folded to single spaces, for the substring test.

    Args:
        value: Any text.

    Returns:
        Lowercased with every run of non-alphanumeric characters replaced by one space,
        padded with a space at each end so a substring test cannot straddle the ends.
    """
    return " " + " ".join(_NOISE.sub(" ", value.lower()).split()) + " "


def _near(wanted: Sequence[str], where: Mapping[str, Sequence[int]]) -> bool:
    """Whether every wanted word appears within ``WINDOW`` tokens of a common point.

    Args:
        wanted: The keyword's folded words, at least two of them.
        where: Folded word to the positions it occupies in the haystack.

    Returns:
        True when some occurrence of the first word has an occurrence of every other
        word within the window on either side.
    """
    anchors = where.get(wanted[0], ())
    for anchor in anchors:
        if all(
            any(abs(position - anchor) <= WINDOW for position in where.get(word, ()))
            for word in wanted[1:]
        ):
            return True
    return False


def found(keyword: str, haystack: str, folded: Sequence[str]) -> bool:
    """Whether one keyword appears in a delivery's words.

    Args:
        keyword: A programme's keyword, as an administrator wrote it.
        haystack: The delivery's text, already through :func:`_normalized`.
        folded: The delivery's text, already through :func:`tokens`.

    Returns:
        True when any of the three tests finds it. See the module docstring for why
        there are three and why the substring test comes first.
    """
    normalized = _normalized(keyword).strip()
    if not normalized:
        return False

    # 1. Normalised substring — preserves every match the old behaviour made.
    if normalized in haystack:
        return True

    wanted = tokens(keyword)
    if not wanted:
        return False

    # 2. Adjacent tokens, singular or plural.
    for start in range(len(folded) - len(wanted) + 1):
        if tuple(folded[start : start + len(wanted)]) == wanted:
            return True

    # 3. The same words close together, in any order. Multi-word keywords only.
    if len(wanted) < 2:
        return False
    where: dict[str, list[int]] = {}
    for position, word in enumerate(folded):
        where.setdefault(word, []).append(position)
    return _near(wanted, where)


def normalized_key(keyword: str) -> str:
    """One keyword reduced to the form two spellings of it share.

    Used wherever a keyword is compared with another keyword rather than with a
    document — checking whether a programme already lists a word, and whether two
    programmes claim the same one — so ``Firm Offer`` and ``firm-offer`` never both end
    up in a list.

    Args:
        keyword: A keyword as somebody wrote it.

    Returns:
        Lowercased with punctuation folded to single spaces, and trimmed.
    """
    return _normalized(keyword).strip()


def discriminating(code: str, keywords: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """A programme's keywords that only that programme claims.

    A word two programmes both list cannot be evidence that a delivery is one of them
    rather than the other. Dropping it is what stops an administrator's overlapping
    vocabulary from making the check confident in the wrong direction — the measured
    version of the defect, where ``snapshot`` and ``historical`` let Archives clear the
    floor in a document about something else.

    Args:
        code: The programme whose keywords to filter.
        keywords: Every programme's keywords.

    Returns:
        The programme's keywords, less any that another programme also lists. Compared
        after normalising, so ``Firm Offer`` and ``firm-offer`` count as the same word.

    Note:
        This filters *evidence for naming another programme*. A programme's own
        keywords are never filtered when looking for the declared programme: a shared
        word still shows the delivery is plausibly what it says it is.
    """
    mine = keywords.get(code, ())
    elsewhere = {
        normalized_key(word) for other, words in keywords.items() if other != code for word in words
    }
    return tuple(word for word in mine if normalized_key(word) not in elsewhere)


def hits(haystack_parts: Iterable[str], keywords: Sequence[str]) -> list[str]:
    """Which of a programme's keywords appear in a delivery.

    Args:
        haystack_parts: The delivery's text, in pieces — OSL sections, configuration
            blocks, report sheet names and headers.
        keywords: The programme's keywords.

    Returns:
        The keywords found, in the order the programme lists them.
    """
    joined = " ".join(haystack_parts)
    haystack = _normalized(joined)
    folded = tokens(joined)
    return [word for word in keywords if found(word, haystack, folded)]
