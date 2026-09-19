"""A last-line check that no prompt carries personal data (ADR-003).

Masking happens at parse time, so an unmasked report value should never reach a prompt
in the first place. This is the backstop for the case where it does: a new stage that
forgets, a fixture that leaks, a parser change that stops masking a column. It runs on
every assembled prompt, inside the adapter, where every call must pass.

It **fails closed**: a suspected match raises rather than warns, because a prompt that
has already left the process cannot be recalled. The cost of a false positive is a
failed run with a clear message; the cost of a false negative is customer data in a
third party's logs.

The patterns are deliberately narrow. A broad "looks like a name" rule would fire on
ordinary requirement text and train people to switch the tripwire off, which is worse
than not having one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Final, Iterable, Pattern

__all__ = ["PiiDetected", "PiiMatch", "scan", "assert_clean", "PATTERNS"]

_LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PiiMatch:
    """What the tripwire found.

    Attributes:
        kind: Which pattern matched, e.g. ``"ssn"``.
        position: Where in the text, so a developer can find it without the value being
            logged.
        sample: A redacted excerpt. Never the matched value itself: this object ends up
            in an exception message, and exception messages reach logs (ADR-003).
    """

    kind: str
    position: int
    sample: str


class PiiDetected(Exception):
    """A prompt looked like it carried personal data and was not sent.

    Carries the pattern names and positions, never the matched text.
    """

    # B042 wants every argument forwarded to ``super().__init__``. Forwarding alone
    # does not make the round-trip work when the signature differs from the stored
    # args; ``__reduce__`` below does, and a test asserts it.
    def __init__(self, matches: Iterable[PiiMatch], stage: str = "") -> None:  # noqa: B042
        """Initialise the error.

        Args:
            matches: What the tripwire found.
            stage: The pipeline stage that assembled the prompt.
        """
        self.matches = tuple(matches)
        self.stage = stage
        kinds = ", ".join(sorted({match.kind for match in self.matches}))
        where = f" in stage {stage}" if stage else ""
        super().__init__(
            f"the prompt{where} looked like it carried personal data ({kinds}) and was not "
            "sent. Masking happens at parse time; check the masked-column list and the "
            "stage that built this prompt."
        )

    def __reduce__(self) -> tuple[type[PiiDetected], tuple[tuple[PiiMatch, ...], str]]:
        """Support pickling across the worker's process boundary.

        Returns:
            The callable and arguments needed to rebuild the error.
        """
        return (type(self), (self.matches, self.stage))


def _compile(pattern: str) -> Pattern[str]:
    """Compile a pattern case-insensitively.

    Args:
        pattern: The regular expression.

    Returns:
        The compiled pattern.
    """
    return re.compile(pattern, re.IGNORECASE)


#: What the tripwire looks for. Each one matches a *format*, not a guess about meaning,
#: so it can be explained to a reviewer who asks why their run failed.
PATTERNS: Final[dict[str, Pattern[str]]] = {
    # 123-45-6789 and 123 45 6789. Not nine bare digits: those are ordinary counts.
    "ssn": _compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
    # 13-to-16 digit card numbers, grouped or not.
    "card_number": _compile(r"\b(?:\d[ -]?){13,16}\b"),
    "email": _compile(r"\b[\w.%+-]+@[\w.-]+\.[a-z]{2,}\b"),
    # (555) 123-4567, 555-123-4567, +1 555 123 4567.
    "phone": _compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)"),
    # A street address: a number followed by a street-type word.
    "street_address": _compile(
        r"\b\d{1,6}\s+[\w\s.]{2,40}\b"
        r"(street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct)\b\.?"
    ),
    "date_of_birth": _compile(r"\b(date[ _]of[ _]birth|dob)\b\s*[:=]\s*\S"),
}

#: Patterns a caller may switch off with a reason. A run's own data can legitimately
#: contain something that looks like a phone number (an account reference, say), and a
#: deployment that hits this repeatedly should narrow the pattern rather than disable
#: the whole tripwire.
DEFAULT_ENABLED: Final[frozenset[str]] = frozenset(PATTERNS)


def scan(text: str, enabled: Iterable[str] = DEFAULT_ENABLED) -> list[PiiMatch]:
    """Look for personal data in an assembled prompt.

    Args:
        text: The prompt, system and user parts joined.
        enabled: Which patterns to apply.

    Returns:
        Every match, empty when the text looks clean. The excerpt in each match is
        redacted, so the result is safe to log.
    """
    active = set(enabled)
    found: list[PiiMatch] = []
    for kind, pattern in PATTERNS.items():
        if kind not in active:
            continue
        for match in pattern.finditer(text):
            found.append(PiiMatch(kind=kind, position=match.start(), sample=_redact(match.group())))
    return found


def _redact(value: str) -> str:
    """Reduce a matched value to its shape.

    Args:
        value: The matched text.

    Returns:
        The same length with every alphanumeric replaced, so a developer can see the
        shape that tripped the rule without the value itself being written down.
    """
    return "".join("*" if character.isalnum() else character for character in value)[:40]


def assert_clean(text: str, stage: str = "", enabled: Iterable[str] = DEFAULT_ENABLED) -> None:
    """Refuse to send a prompt that looks like it carries personal data.

    Args:
        text: The prompt, system and user parts joined.
        stage: The pipeline stage, named in the error.
        enabled: Which patterns to apply.

    Raises:
        PiiDetected: When anything matches. Fails closed on purpose: a prompt already
            sent cannot be recalled.
    """
    matches = scan(text, enabled)
    if not matches:
        return
    _LOG.error(
        "PII tripwire blocked a prompt in stage %s: %s",
        stage or "unknown",
        ", ".join(f"{m.kind}@{m.position}" for m in matches),
    )
    raise PiiDetected(matches, stage)
