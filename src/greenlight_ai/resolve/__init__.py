"""Which sheet, column or label did they mean? (Phase 6.21a).

Every comparison in this product eventually reaches a *name* somebody else chose — a
worksheet, a column header, a row label, a configuration key. Until this package the
codebase answered "is this the one?" in four places with four slightly different rules,
and every one of them stopped at exact-after-lowercasing. A real report whose attribute
sheet is called ``Attribute Summary`` matched nothing, and every check that needed it
became a "could not evaluate" finding: honest, and no validation at all.

So the answer lives in one place and it is a **ladder**, tried in order and stopping at
the first unambiguous answer:

1. **exact** — case and surrounding space aside. What every caller did before this
   package existed, so nothing that matched then stops matching now.
2. **squashed** — separators are noise. ``opt_out``, ``optOut`` and ``OPT-OUT`` are one
   name; so are ``Delivered_count`` and ``Delivered  count``.
3. **tokens** — the same words, singular or plural, in order. This is the rung that
   finds ``Attribute Summary`` for ``Attributes``, and it is deliberately the fussiest
   of the three: the words must match as a set or as an ordered run with at most a
   couple of extra words around them.
4. **alternate** — what a person wrote down. No amount of normalising reaches a report
   that calls the delivered count *Records shipped*; only somebody who knows the
   delivery does.
5. **model** — :mod:`greenlight_ai.resolve.locate`, and only where the four above
   failed. It is shown **names, never values**, its answer must be one of the names it
   was offered, and a confidence floor applies. It is never a pass: what it resolves
   becomes a review-severity record a person confirms (ADR-001).

**A rung that ties is a rung that failed.** Two candidates matching equally well is not
an answer, and guessing between them would be the comparison ADR-001 keeps out of the
model's hands — so the ladder falls through to the next rung, and eventually to the
model with every candidate still on the table.

This module holds rungs 1 to 4 and depends on nothing. Rung 5 lives in
:mod:`greenlight_ai.resolve.locate` and rung 5's bookkeeping in
:mod:`greenlight_ai.resolve.layout`; both are imported by path so that
:mod:`greenlight_ai.parsers`, which needs only the normalisers, never pulls in
:mod:`greenlight_ai.llm`.
"""

from __future__ import annotations

from greenlight_ai.resolve.ladder import (
    DETERMINISTIC_RUNGS,
    RUNGS,
    Resolution,
    Rung,
    resolve,
)
from greenlight_ai.resolve.normalize import (
    fold,
    padded,
    spaced,
    squashed,
    tokens,
)

__all__ = [
    "DETERMINISTIC_RUNGS",
    "RUNGS",
    "Resolution",
    "Rung",
    "fold",
    "padded",
    "resolve",
    "spaced",
    "squashed",
    "tokens",
]
