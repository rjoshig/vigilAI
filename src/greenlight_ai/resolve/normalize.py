"""Reducing a name to a comparable form, once, for the whole product.

Before Phase 6.21 four modules did this with four slightly different rules:
``compliance_match.normalize_segment`` dropped separators entirely and array indices
with them, ``parsers.base._normalise_label`` dropped separators entirely,
``field_labels.normalize_label`` collapsed them to one space, and
``programme_match.fold``/``tokens`` folded plurals on top. Three of those differences
were accidental and the fourth — space kept or removed — is real, because a substring
test needs word boundaries and an equality test does not.

So there are two normalisers and they are both here:

* :func:`squashed` removes separators. Use it to ask *is this the same name?*
* :func:`spaced` collapses them to one space. Use it to ask *does this name appear
  inside that text?*, where a boundary matters.

On top of them :func:`fold` and :func:`tokens` reduce words to a form that compares
across singular and plural. They are deliberately not a stemmer: a stemmer would fold
tense and derivation too, which none of the callers need and which makes a false match
harder to explain to the person reading the finding it produced.

Nothing here imports anything from this package or any other, which is what lets
:mod:`greenlight_ai.parsers` use it.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "MIN_FOLD",
    "fold",
    "padded",
    "spaced",
    "squashed",
    "tokens",
]

#: Anything that is not a letter or a digit separates words. Hyphens, underscores,
#: spaces, punctuation and an array index's brackets all fall here.
_NOISE: Final = re.compile(r"[^a-z0-9]+")

#: Below this length a trailing ``s`` is more likely to be part of the word than a
#: plural, so the fold leaves it alone. ``is`` and ``as`` are not plurals.
MIN_FOLD: Final[int] = 4


def squashed(value: str) -> str:
    """Reduce a name to a form that compares when separators differ.

    Args:
        value: A name as configured, or as an artifact writes it.

    Returns:
        Lowercased with every non-alphanumeric character removed, so ``opt_out``,
        ``optOut``, ``OPT-OUT`` and ``rules[2]``/``rules2`` all compare alike. An empty
        string in gives an empty string out, which callers treat as "no name".
    """
    return _NOISE.sub("", value.strip().lower())


def spaced(value: str) -> str:
    """Reduce text to a form that compares when word boundaries matter.

    Args:
        value: Any text — a label, a header, a document's prose.

    Returns:
        Lowercased with every run of non-alphanumeric characters replaced by one space
        and the ends trimmed, so ``As-of Date``, ``as_of date`` and ``As of  Date`` all
        compare alike while ``asofdate`` stays distinct from ``as of date``.
    """
    return " ".join(_NOISE.sub(" ", value.strip().lower()).split())


def padded(value: str) -> str:
    """:func:`spaced`, with a space at each end.

    Args:
        value: Any text.

    Returns:
        The spaced form wrapped in single spaces, so a substring test for
        ``" review "`` cannot straddle the start or the end of the haystack and cannot
        match the middle of a longer word.
    """
    return f" {spaced(value)} "


def fold(token: str) -> str:
    """Reduce one word to a form that compares across singular and plural.

    Args:
        token: One normalised word.

    Returns:
        The word with a plural ending removed, or unchanged when removing one would be
        a guess. ``accounts`` folds to ``account`` and ``policies`` to ``policy``;
        ``across``, ``is`` and ``gross`` do not fold.
    """
    if len(token) >= MIN_FOLD + 1 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) >= MIN_FOLD and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(value: str) -> tuple[str, ...]:
    """Split text into normalised, singular-folded words.

    Args:
        value: Any text — a document's prose, a configuration path, a column header.

    Returns:
        The words, lowercased, stripped of punctuation, and folded. ``Attribute
        Summary`` and ``ATTRIBUTES`` share the token ``attribute``.
    """
    return tuple(fold(word) for word in _NOISE.sub(" ", value.lower()).split() if word)
