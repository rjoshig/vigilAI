"""Findings nobody authored a rule for (Phase 6.21c).

Every other finding this product makes traces back to a rule: an OSL requirement, a
compliance control, a check an administrator wrote. This one does not. It asks a
different question — *is this delivery shaped like the ones before it?* — and the only
honest baseline for that is the configuration's own history.

**The method, stated so it can be argued with.** For each attribute and each measure
(:data:`greenlight_ai.checks.profile.MEASURES`), take the values from the previous
finalized runs of the same configuration. Compare this delivery against their
**median** and their **median absolute deviation**, not their mean and standard
deviation: with five or ten runs of history a single odd delivery drags a mean far
enough to hide the next one, and the median does not move. Where the history is
perfectly flat — the same number every time, which happens with a minimum a filter
pins — MAD is zero and no multiple of it means anything, so a **relative** threshold
applies instead.

**What it will not do.**

- It says nothing until there is enough history (:data:`MIN_HISTORY` by default).
  A baseline of one delivery is not a baseline, and a tool that invented one would
  teach reviewers to ignore it in its first week.
- It grades everything **low**. Code cannot know whether a mean moving 3% matters for
  this attribute in this business, and severity is code's to set (ADR-001) — so it
  sets the one that says *look at this when you have a moment* and puts the numbers in
  the finding for a person to judge.
- It never compares across configurations. Two deliveries for different configurations
  are not the same thing measured twice.

The second half of 6.21c — the model reading the same aggregates and saying what looks
unusual — lives in :func:`read_shape`. It is off by default, because it spends a call
on every run, and it grades nothing either: code turns what it says into a review item.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Final, Mapping, Sequence

from greenlight_ai.checks.profile import MEASURE_LABEL, MEASURES, AttributeProfile, measure_of

__all__ = [
    "MIN_HISTORY",
    "RELATIVE_FLOOR",
    "SENSITIVITY",
    "Deviation",
    "compare",
    "describe",
]

_LOG: Final = logging.getLogger(__name__)

#: How many previous finalized runs of the same configuration are needed before this
#: says anything at all. Three is a starting point and is settable; the number that
#: survives contact with real deliveries is a Phase 7 question.
MIN_HISTORY: Final[int] = 3

#: How many robust standard deviations from the median is far. Four is deliberately
#: generous: the cost of a false anomaly is a reviewer learning to ignore the whole
#: category, and the cost of a missed one is a finding somebody else would have caught.
SENSITIVITY: Final[float] = 4.0

#: What counts as far when the history is perfectly flat and no multiple of its spread
#: means anything. A fifth off a number that has never moved is worth a look.
RELATIVE_FLOOR: Final[float] = 0.20

#: Turns a median absolute deviation into something comparable with a standard
#: deviation, for a normal distribution. The constant is standard; it is named here so
#: nobody has to recognise 1.4826.
_MAD_TO_SIGMA: Final[float] = 1.4826

#: Below this a number is treated as zero for the relative test, so a mean that wobbles
#: around 0.0000001 does not produce an infinite ratio.
_NEAR_ZERO: Final[float] = 1e-9


@dataclass(frozen=True, slots=True)
class Deviation:
    """One measure of one attribute, far from its own history.

    Attributes:
        attribute: The attribute, as this delivery writes it.
        measure: Which measure moved, from :data:`MEASURES`.
        value: What this delivery reported.
        median: The middle of what the previous deliveries reported.
        history: How many previous deliveries were compared against.
        multiple: How many robust deviations away this is, or ``0.0`` when the history
            was flat and the relative test decided it.
        share: How far off the median it is as a share of the median, for the flat case
            and for the sentence a reviewer reads.
    """

    attribute: str
    measure: str
    value: float
    median: float
    history: int
    multiple: float = 0.0
    share: float = 0.0

    @property
    def title(self) -> str:
        """One line for the finding's title."""
        return (
            f"{self.attribute}: the {MEASURE_LABEL.get(self.measure, self.measure)} "
            f"is unlike this configuration's previous deliveries"
        )


def _spread(values: Sequence[float], middle: float) -> float:
    """The robust spread of a history, comparable with a standard deviation.

    Args:
        values: The previous deliveries' values.
        middle: Their median.

    Returns:
        ``1.4826 × MAD``, or ``0.0`` when every value is identical.
    """
    return _MAD_TO_SIGMA * statistics.median([abs(value - middle) for value in values])


def _far(
    value: float, middle: float, spread: float, sensitivity: float
) -> tuple[bool, float, float]:
    """Whether one value is far from its history, and by how much.

    Args:
        value: What this delivery reported.
        middle: The median of the previous deliveries.
        spread: Their robust spread.
        sensitivity: How many spreads is far.

    Returns:
        ``(far, multiple, share)``. ``multiple`` is zero when the history was flat and
        the relative test decided it, which is the case the finding words differently.
    """
    share = abs(value - middle) / abs(middle) if abs(middle) > _NEAR_ZERO else 0.0
    if spread <= _NEAR_ZERO:
        # A history that never moved. A multiple of nothing is nothing, so the question
        # becomes proportional: is this a big change against a number that was fixed?
        if abs(middle) <= _NEAR_ZERO:
            return abs(value) > _NEAR_ZERO, 0.0, 0.0
        return share > RELATIVE_FLOOR, 0.0, share
    multiple = abs(value - middle) / spread
    return multiple > sensitivity, multiple, share


def compare(
    current: Mapping[str, AttributeProfile],
    history: Sequence[Mapping[str, AttributeProfile]],
    sensitivity: float = SENSITIVITY,
    min_history: int = MIN_HISTORY,
) -> list[Deviation]:
    """Find every measure this delivery reports that its history does not explain.

    Args:
        current: This delivery's profile, by canonical attribute name.
        history: The previous finalized deliveries' profiles, newest first. Order does
            not matter to the arithmetic; it is only used to bound how many are read.
        sensitivity: How many robust deviations from the median is far.
        min_history: How many previous deliveries are needed before anything is said.

    Returns:
        The deviations, attribute then measure. Empty when there is not enough history,
        which is the ordinary state for a configuration's first few runs and is not an
        error.
    """
    if len(history) < min_history:
        _LOG.info(
            "anomaly: %d previous deliveries, %d needed; saying nothing",
            len(history),
            min_history,
        )
        return []

    found: list[Deviation] = []
    for name, profile in sorted(current.items()):
        for measure in MEASURES:
            value = measure_of(profile, measure)
            if value is None:
                continue
            # Only deliveries that reported this measure count. An attribute that
            # gained a mean column last month has a history of one, not of ten.
            seen = [
                past
                for past in (measure_of(entry[name], measure) for entry in history if name in entry)
                if past is not None
            ]
            if len(seen) < min_history:
                continue

            middle = statistics.median(seen)
            far, multiple, share = _far(value, middle, _spread(seen, middle), sensitivity)
            if far:
                found.append(
                    Deviation(
                        attribute=profile.name or name,
                        measure=measure,
                        value=value,
                        median=middle,
                        history=len(seen),
                        multiple=multiple,
                        share=share,
                    )
                )
    _LOG.info("anomaly: %d deviation(s) against %d deliveries", len(found), len(history))
    return found


def describe(deviation: Deviation) -> str:
    """The sentence a reviewer reads, with the numbers that produced it.

    A finding nobody authored a rule for has to carry its own justification, because
    there is no rule to point at. So it says what it saw, what it expected, how far
    apart they are and how much history that rests on — and it says plainly that being
    unusual is not the same as being wrong.

    Args:
        deviation: What moved.

    Returns:
        The detail text.
    """
    label = MEASURE_LABEL.get(deviation.measure, deviation.measure)
    if deviation.measure == "null_rate":
        seen = f"{deviation.value:.1%}"
        usual = f"{deviation.median:.1%}"
    else:
        seen = f"{deviation.value:,.4g}"
        usual = f"{deviation.median:,.4g}"

    if deviation.multiple > 0:
        distance = (
            f"{deviation.multiple:.1f} times as far from that as this configuration's "
            "deliveries usually sit"
        )
    else:
        distance = (
            f"{deviation.share:.0%} away from a figure that has not moved across those "
            "deliveries"
        )

    return (
        f"The {label} for {deviation.attribute} is {seen}, against {usual} across the "
        f"previous {deviation.history} finalized deliveries of this configuration — "
        f"{distance}. No rule covers this: it is a comparison against the delivery's own "
        "history, reported because it is unusual, which is not the same as being wrong. "
        "Confirm it is expected, or say what it should have been."
    )
