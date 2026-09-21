"""Fitting text into a prompt, and saying what was left out (Phase 8b).

These two functions were `_clip` and `_fit` in `pipeline/guidance.py`, where they had
exactly one caller. Phase 8's chat pack needs the same discipline — a whole-block
ceiling, oldest lines dropped first, and the omission stated rather than silent — and
`api/` may never import `pipeline/` (`architecture.md`). Copying them into `chat/` would
have left two implementations of the rule that decides what a model is not shown, which
is the kind of divergence nobody notices until an answer is wrong for a reason that is
not in the diff.

So they moved **down** into a module with no dependencies rather than sideways into a
second copy. `pipeline/` and `chat/` both import it; neither imports the other.

**The rule both callers obey.** A block that is too long loses its *oldest* lines,
because the newest note is the one somebody wrote most recently about this delivery —
and what was dropped is said out loud. A model told nine of ten notes must not believe
it has ten, and a reader given an answer built from a trimmed pack deserves to know the
pack was trimmed.
"""

from __future__ import annotations

import logging
from typing import Final, Sequence

__all__ = ["clip", "fit", "Fitted"]

_LOG: Final = logging.getLogger(__name__)


def clip(text: str, cap: int, what: str = "text") -> str:
    """Trim one field to a cap, at a word boundary.

    Args:
        text: The text to trim. Whitespace is collapsed first, so a pasted block does
            not spend its allowance on newlines.
        cap: The ceiling, in characters.
        what: What this is, for the log line.

    Returns:
        The text, truncated at a word boundary with an ellipsis when it is too long.
    """
    cleaned = " ".join(text.split())
    if len(cleaned) <= cap:
        return cleaned
    cut = cleaned[:cap].rsplit(" ", 1)[0]
    _LOG.info("%s truncated from %d to %d characters", what, len(cleaned), len(cut))
    return f"{cut}…"


class Fitted(str):
    """A rendered block that remembers how many lines it lost.

    A plain string would have made the caller count twice — once here to trim and once
    there to report — and the second count is the one that drifts. Subclassing `str`
    keeps every existing caller unchanged: `fit(...)` is still a string everywhere it
    was before, and the extra fact is there for the caller that needs it.

    Attributes:
        dropped: How many lines were omitted. Zero when everything fitted.
        total: How many lines there were before trimming.
    """

    dropped: int = 0
    total: int = 0

    def __new__(cls, value: str, dropped: int = 0, total: int = 0) -> "Fitted":
        """Build the string and attach the counts.

        Args:
            value: The rendered block.
            dropped: How many lines were omitted.
            total: How many there were to begin with.

        Returns:
            The string, carrying both counts.
        """
        fitted = super().__new__(cls, value)
        fitted.dropped = dropped
        fitted.total = total
        return fitted


def fit(lines: Sequence[str], what: str, cap: int, bullet: bool = True) -> Fitted:
    """Render lines within a whole-block ceiling, oldest first to go.

    Args:
        lines: The lines to render, oldest first.
        what: What a dropped line is called, for the note that replaces it.
        cap: The ceiling on the whole block, in characters.
        bullet: Whether to prefix each line with a dash.

    Returns:
        The rendered block, carrying how many lines were dropped.
    """
    rendered = [f"- {line}" if bullet else line for line in lines]
    total = sum(len(line) + 1 for line in rendered)
    if total <= cap:
        return Fitted("\n".join(rendered), dropped=0, total=len(rendered))

    kept: list[str] = []
    used = 0
    for line in reversed(rendered):
        if used + len(line) + 1 > cap:
            break
        kept.append(line)
        used += len(line) + 1
    kept.reverse()
    dropped = len(rendered) - len(kept)
    _LOG.info("%s block trimmed: %d of %d dropped", what, dropped, len(rendered))
    marker = f"({dropped} older {what}(s) omitted to keep this prompt short.)"
    return Fitted(
        "\n".join([f"- {marker}" if bullet else marker, *kept]),
        dropped=dropped,
        total=len(rendered),
    )
