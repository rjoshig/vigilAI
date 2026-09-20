"""What a reviewer has stopped needing to see (Phase 6.18a).

The tool already knows which findings people wave through: every review records a
verdict, and a per-rule tally has been displayed on the training screen since Phase
6.13. **Nothing read it.** This module does, and it is the first half of the phase that
lets a reviewer stop reading every finding and read only the ones that matter.

## What it does, and what it deliberately does not

It groups findings into **signatures** — "this same finding again" — counts the verdicts
people gave each signature, and decides whether a signature has earned its way out of
the review queue. That decision is **arithmetic over verdicts a person gave** (ADR-001).
The model is not asked whether a finding is important, and a model's confidence score is
not evidence here; only a human verdict is.

**It ships computing and recording, and showing nobody.** A signature that meets the bar
is marked :data:`WOULD_DEMOTE`, and every reviewer still sees every finding. This is the
same way a learned rule earns its way in (ADR-021): a thing runs and is counted before it
changes what anyone sees, so the question *"it would have hidden these forty — was any of
them real?"* can be asked from evidence rather than from hope. Acting on the decision
needs the maturity levels of 6.18b and the trust numbers of 6.18c.

## The rules, and why each is what it is

**A signature is per customer, per programme, per rule, and per the thing it fired on.**
A blank score column and a blank state column are two different findings however much
they share a rule: learning that one is harmless must never silence the other. Trust is
shared across a customer's deliveries within one programme and never across programmes,
because a control genuinely is implemented differently under Account Solicitation than
under Archives.

**Ten occurrences, and every one of them waved through.** Not a rate — a count, with no
exceptions in it. "It was shown to a person ten times and never once mattered" is a
sentence that can be said to an auditor. Nine of ten cannot, because the tenth is the
one that would have been hidden.

**One upheld finding blocks the signature permanently**, until a person clears it. A
reviewer who marked something *confirmed* — or *accepted_risk*, which means the finding
was real and someone chose to live with it — has said that finding is true. No number of
later dismissals outranks that.

**High and above are never demoted**, at any level of evidence. The goal is a reviewer
who sees only the high and critical findings, not a reviewer who eventually sees nothing.

**Nothing returns on its own.** A demoted signature stays demoted until a person restores
it or a new verdict upholds it, which matches ADR-021's rule that nothing in the training
record expires by itself.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Final, Iterable, Sequence

__all__ = [
    "BLOCKED",
    "DISMISSING_VERDICTS",
    "MIN_OCCURRENCES",
    "NEVER_DEMOTED",
    "STATES",
    "Tally",
    "UPHOLDING_VERDICTS",
    "WATCHING",
    "WOULD_DEMOTE",
    "decide",
    "signature",
    "tally",
]

_LOG: Final = logging.getLogger(__name__)

#: Not enough evidence yet, or not enough of the right kind.
WATCHING: Final[str] = "watching"
#: The bar is met. In 6.18a this is recorded and acted on by nobody.
WOULD_DEMOTE: Final[str] = "would_demote"
#: A person has upheld this finding at least once. Never demotable until they clear it.
BLOCKED: Final[str] = "blocked"

#: Every state a signature can be in.
STATES: Final[tuple[str, ...]] = (WATCHING, WOULD_DEMOTE, BLOCKED)

#: A verdict that says the finding did not matter.
DISMISSING_VERDICTS: Final[frozenset[str]] = frozenset({"false_positive"})

#: A verdict that says the finding was real. ``accepted_risk`` belongs here and not with
#: the dismissals: the reviewer agreed the finding was true and chose to carry it, which
#: is the opposite of saying it should never have been raised.
UPHOLDING_VERDICTS: Final[frozenset[str]] = frozenset({"confirmed", "accepted_risk"})

#: How many times a signature must have been shown to a person, and waved through every
#: single time, before it has earned its way out of the queue.
MIN_OCCURRENCES: Final[int] = 10

#: Severities no amount of evidence demotes. The aim is a reviewer who reads only the
#: serious findings, not one who reads none.
NEVER_DEMOTED: Final[frozenset[str]] = frozenset({"high", "critical"})


def signature(
    *,
    customer_name: str,
    scope: str,
    rule_ref: str,
    finding_type: str,
    element_ref: str,
) -> str:
    """The stable identity of "this same finding again".

    Args:
        customer_name: The customer the delivery belongs to.
        scope: The delivery programme's code, or empty when the submitter did not say.
        rule_ref: The rule or check that produced the finding.
        finding_type: The kind of finding.
        element_ref: What it fired on — the field, cell or requirement. Two findings
            from one rule about two different things are two signatures.

    Returns:
        A hex digest of the five parts. A digest rather than a joined string because it
        is an index key and a foreign concept to a reader either way, and because the
        parts are stored alongside it for anyone who needs to read them.

    Note:
        The run is deliberately not part of this, and neither is the finding's wording.
        A signature that changed whenever a title was reworded would never accumulate
        the evidence this is for.
    """
    parts = [
        customer_name.strip().lower(),
        scope.strip().upper(),
        rule_ref.strip(),
        finding_type.strip(),
        element_ref.strip(),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:40]


@dataclass(frozen=True, slots=True)
class Tally:
    """What people decided about one signature.

    Attributes:
        occurrences: How many times a person recorded any verdict on it. Findings
            nobody has looked at are not counted: an undecided finding is not evidence.
        dismissed: How many of those said it did not matter.
        upheld: How many said it was real — confirmed, or accepted as a known risk.
        severities: The severities it has fired at.
        run_ids: The runs whose verdicts make up this tally, oldest first.
    """

    occurrences: int = 0
    dismissed: int = 0
    upheld: int = 0
    severities: frozenset[str] = frozenset()
    run_ids: tuple[int, ...] = ()


def tally(verdicts: Iterable[tuple[str, str, int]]) -> Tally:
    """Count the verdicts recorded against one signature.

    Args:
        verdicts: ``(review_status, severity, run_id)`` for every finding sharing the
            signature, oldest first.

    Returns:
        The tally. Undecided findings are skipped rather than counted as either kind:
        a finding nobody has judged says nothing about whether it mattered.
    """
    occurrences = dismissed = upheld = 0
    severities: set[str] = set()
    runs: list[int] = []
    for status, severity, run_id in verdicts:
        if status in DISMISSING_VERDICTS:
            dismissed += 1
        elif status in UPHOLDING_VERDICTS:
            upheld += 1
        else:
            continue
        occurrences += 1
        severities.add(severity)
        runs.append(run_id)
    return Tally(
        occurrences=occurrences,
        dismissed=dismissed,
        upheld=upheld,
        severities=frozenset(severities),
        run_ids=tuple(runs),
    )


def decide(counted: Tally, *, minimum: int = MIN_OCCURRENCES) -> tuple[str, str]:
    """Whether a signature has earned its way out of the review queue.

    Args:
        counted: The tally of verdicts people gave it.
        minimum: How many dismissals are needed. The shipped default is
            :data:`MIN_OCCURRENCES`; the console can raise it but the reasoning below
            does not change.

    Returns:
        The state, and one sentence saying why — which is stored and shown, because a
        demotion nobody can explain is one nobody should trust.
    """
    if counted.upheld:
        return (
            BLOCKED,
            f"A reviewer judged this finding real {counted.upheld} time(s). "
            "One upheld finding outranks any number of dismissals, so this can only "
            "be demoted by a person clearing it.",
        )
    serious = sorted(counted.severities & NEVER_DEMOTED)
    if serious:
        return (
            BLOCKED,
            f"Fires at {', '.join(serious)} severity, which is never demoted at any "
            "level of evidence. A reviewer should end up reading the serious findings, "
            "not none of them.",
        )
    if counted.occurrences < minimum:
        return (
            WATCHING,
            f"Waved through {counted.dismissed} time(s); {minimum} are needed, with no "
            "exceptions among them.",
        )
    return (
        WOULD_DEMOTE,
        f"Shown to a reviewer {counted.occurrences} time(s) and waved through every "
        "time. It has earned its way out of the queue.",
    )


def justifying_runs(counted: Tally, *, limit: int = 20) -> tuple[int, ...]:
    """The runs whose verdicts a demotion rests on.

    Args:
        counted: The tally.
        limit: How many to keep. The most recent, because those are the ones somebody
            checking the decision will want to open.

    Returns:
        The run ids, oldest first, at most ``limit`` of them.
    """
    return tuple(counted.run_ids[-limit:]) if limit > 0 else ()


def summarize(states: Sequence[str]) -> dict[str, int]:
    """Count signatures by state, for the shadow report.

    Args:
        states: Each signature's state.

    Returns:
        State to how many signatures are in it, including the states with none.
    """
    return {state: sum(1 for value in states if value == state) for state in STATES}
