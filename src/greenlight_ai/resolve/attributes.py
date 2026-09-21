"""Does this artifact carry this attribute, and how do we know? (Phase 6.22a).

Three modules asked that question and all three asked it the same wrong way: a dict
lookup on a normalised string, `resolve(name) not in stats`. When it missed,
:func:`greenlight_ai.checks.reports._check_fields_present` reported the attribute as
**missing at high severity**, while :func:`_check_bound` reported the very same miss as
*could not evaluate*. Two paths, one question, two answers — and the louder one was
wrong, because an OSL that says ``AT01`` against a DIRT column named
``debsc_burs_atyrt_at01_1`` describes a delivery that is entirely correct.

The repair is to stop conflating two states that happen to share a code path:

* **the artifact does not carry this attribute** — a real defect, and the finding the
  old code was written for;
* **we could not work out what this artifact calls it** — not a defect at all, and
  nothing a reviewer should see at the top of the severity scale.

:func:`present` tells them apart with evidence rather than assumption. It resolves
through the one ladder (ADR-054), and where the ladder fails it reports the candidates
code narrowed to but could not decide between. An empty shortlist means nothing in the
artifact resembles the wanted name, which is the honest reading of *missing*; a
non-empty one means the answer is probably in front of us and we cannot prove which,
which is the honest reading of *could not evaluate*.

The shortlist **only ever narrows**. It never picks: choosing between two plausible
candidates is the comparison ADR-001 keeps out of a guess's hands, and in a later part
of this phase it is what the model is shown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Final, Sequence

from greenlight_ai.resolve.ladder import Resolution, Rung, resolve
from greenlight_ai.resolve.normalize import fold, squashed, tokens

__all__ = [
    "MAX_NEAR",
    "AttributeMatch",
    "near_names",
    "present",
]

_LOG: Final = logging.getLogger(__name__)

#: How many near misses a finding quotes. Enough for a reviewer to recognise the answer,
#: few enough that the detail stays a sentence rather than a column dump.
MAX_NEAR: Final[int] = 5

#: A token this short carries no evidence — ``at`` shared between ``AT01`` and
#: ``at_risk_flag`` is a coincidence, not a resemblance. The floor the ladder's own
#: token rung uses for the same reason.
_MIN_TOKEN: Final[int] = 3

#: A name must be at least this long before *containing* one counts as resembling it.
#: Without a floor, ``ST`` resembles ``INCOME_EST`` (``st`` sits inside ``incomeest``)
#: and a genuinely undelivered attribute would be softened to "could not evaluate" —
#: the opposite of this module's purpose. Four is the shortest length at which a
#: substring is evidence rather than a coincidence of spelling.
_MIN_SUBSTRING: Final[int] = 4


@dataclass(frozen=True, slots=True)
class AttributeMatch:
    """Whether an artifact carries one attribute, and on what evidence.

    Attributes:
        wanted: The attribute as the OSL asked for it.
        found: The name the artifact spells it with, or ``None`` when unresolved. This
            is what a caller must use to read the artifact.
        rung: Which rung of the ladder reached it, or ``None``.
        confidence: ``1.0`` for the deterministic rungs, the model's own number for the
            fifth. Code applies the floor; this only reports.
        near: Candidates code narrowed to but could not decide between. Empty means
            nothing in the artifact resembles the wanted name.
        reason: One line a reviewer can read.
    """

    wanted: str
    found: str | None = None
    rung: Rung | None = None
    confidence: float = 0.0
    near: tuple[str, ...] = ()
    reason: str = ""

    @property
    def resolved(self) -> bool:
        """Whether the artifact carries this attribute.

        Returns:
            ``True`` when some rung reached a name.
        """
        return self.found is not None

    @property
    def reasoned(self) -> bool:
        """Whether the model reached it rather than code.

        Returns:
            ``True`` when the fifth rung answered.
        """
        return self.rung == "model"

    @property
    def plausible(self) -> bool:
        """Whether the answer is probably present but unproven.

        This is the test that decides between *missing* and *could not evaluate*, so it
        is deliberately the only place that judgement is made.

        Returns:
            ``True`` when the attribute did not resolve but something resembles it.
        """
        return not self.resolved and bool(self.near)


def _contains(inner: str, outer: str) -> bool:
    """Whether ``outer`` carries ``inner`` as evidence rather than as a coincidence.

    Args:
        inner: The squashed name looked for.
        outer: The squashed name looked in.

    Returns:
        ``True`` when ``inner`` is long enough to mean something and sits inside
        ``outer``.
    """
    return len(inner) >= _MIN_SUBSTRING and inner in outer


def near_names(wanted: str, candidates: Sequence[str]) -> tuple[str, ...]:
    """The candidates that resemble ``wanted`` closely enough to be worth naming.

    Three tests, all deterministic and all reproducible by a person reading the
    workbook:

    * the whole wanted name appears as **one of the candidate's words**, or the other
      way round. This is the strongest of the three and the only one that works for a
      short name: ``ST`` standing as its own word inside ``debsc_burs_atyrt_st_1`` is
      evidence, where the two letters ``st`` buried in ``incomeest`` are not.
    * one squashed name **contains** the other, with a length floor — what reaches
      ``AT01`` inside ``debsc_burs_atyrt_at01_1``;
    * the two share a word long enough to mean something.

    Args:
        wanted: The attribute as the OSL asked for it.
        candidates: The names the artifact offers.

    Returns:
        The resembling candidates in the order the artifact lists them, at most
        :data:`MAX_NEAR`. Empty when nothing resembles it, which the caller must read
        as *the artifact does not carry this*.
    """
    key = squashed(wanted)
    if not key:
        return ()
    wanted_tokens = tuple(tokens(wanted))
    wanted_whole = {fold(word) for word in wanted_tokens}
    wanted_words = {fold(word) for word in wanted_tokens if len(word) >= _MIN_TOKEN}

    found: list[str] = []
    for candidate in candidates:
        other = squashed(candidate)
        if not other:
            continue
        candidate_tokens = tuple(tokens(candidate))
        whole = {fold(word) for word in candidate_tokens}
        if fold(key) in whole or fold(other) in wanted_whole:
            found.append(candidate)
            continue
        if _contains(key, other) or _contains(other, key):
            found.append(candidate)
            continue
        words = {fold(word) for word in candidate_tokens if len(word) >= _MIN_TOKEN}
        if wanted_words & words:
            found.append(candidate)

    # Same string twice is one near miss: a workbook repeating a column name is not an
    # ambiguity anybody can act on.
    return tuple(dict.fromkeys(found))[:MAX_NEAR]


def present(
    wanted: str,
    candidates: Sequence[str],
    *,
    alternates: Sequence[str] = (),
    canonical: Callable[[str], str] | None = None,
) -> AttributeMatch:
    """Decide whether an artifact carries one attribute.

    The order matters and is the ADR-054 promise restated: whatever matched before this
    function existed still matches, and the new tolerance is only ever reached after the
    old answer has failed.

    Args:
        wanted: The attribute as the OSL asked for it.
        candidates: The names the artifact offers, spelled as it spells them.
        alternates: Spellings a person or the dictionary supplied, tried as the
            ladder's fourth rung.
        canonical: The legacy alias resolver, applied to both sides. Passing it
            reproduces the pre-6.22 lookup exactly, so a seeded alias table behaves as
            it always did.

    Returns:
        The match. ``resolved`` says the artifact carries it; ``plausible`` distinguishes
        *could not evaluate* from *missing*.
    """
    if not wanted.strip():
        return AttributeMatch(wanted=wanted, reason="The rule names no attribute.")

    # 1. The legacy lookup, unchanged. An alias somebody seeded must keep working, and
    #    it must keep winning, or this repair would quietly change what matches.
    if canonical is not None:
        by_key: dict[str, str] = {}
        for candidate in candidates:
            by_key.setdefault(canonical(candidate), candidate)
        hit = by_key.get(canonical(wanted))
        if hit is not None:
            return AttributeMatch(
                wanted=wanted,
                found=hit,
                rung="exact",
                confidence=1.0,
                reason=f"{wanted!r} is {hit!r} in this artifact.",
            )

    # 2. The ladder: separators as noise, then the same words, then a spelling somebody
    #    wrote down. Rung 5 is not reached from here — the model is asked in 6.22d,
    #    where the shortlist below is what it is shown.
    resolution: Resolution | None = resolve(wanted, candidates, alternates)
    if resolution is not None:
        return AttributeMatch(
            wanted=wanted,
            found=resolution.value,
            rung=resolution.rung,
            confidence=resolution.confidence,
            reason=resolution.reason,
        )

    # 3. Nothing resolved. Whether that is a defect or an unanswered question depends
    #    entirely on whether anything here resembles what was asked for.
    near = near_names(wanted, candidates)
    if near:
        _LOG.info("attribute %r unresolved; %d near miss(es)", wanted, len(near))
        return AttributeMatch(
            wanted=wanted,
            near=near,
            reason=(f"Could not tell which column is {wanted!r}. " f"Closest: {', '.join(near)}."),
        )
    return AttributeMatch(
        wanted=wanted,
        reason=f"Nothing in this artifact resembles {wanted!r}.",
    )
