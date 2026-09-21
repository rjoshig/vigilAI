"""Who is using the tool, and who is having a hard time with it (Phase 6.19).

The usage dashboard has always counted runs for the deployment as a whole, which
answers *is anybody using this* and nothing else. The question an administrator
actually arrives with is narrower: **is this going badly for a particular group of
people?** A team whose runs fail twice as often as everybody else's is either meeting a
report layout the parsers do not handle, or has been taught the product wrong. Both are
fixable, and neither is visible in a single deployment-wide failure rate.

So the counting is per person, and it separates the three ways a run can go wrong,
because they have different causes and different fixes:

- **Failed** — the pipeline raised. Usually the tool's problem: a layout, a parser, a
  model call that would not come back.
- **Held** — the uploaded artifacts disagreed with what was typed on the form
  (ADR-041). Usually a person's problem, and the most teachable of the three: the wrong
  month's configuration, a customer name that does not match the file.
- **Re-run** — the same order submitted again. Something was wrong the first time,
  whoever's fault it was.

**Rates are shown against the deployment's own average**, not against a number somebody
invented. "Twice everyone else" is a fact an administrator can act on; "a score of 68"
is not, and nobody can argue with it.

Nothing here is a judgment on a person. It is a count of what happened, and the reason
it is per user rather than per team is that the tool knows who submitted a run and does
not know what team anybody is on.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Final, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai import spend
from greenlight_ai.db import models

__all__ = ["PERIODS", "DEFAULT_DAYS", "DayCount", "UserUsage", "UsagePeriod", "build"]

_LOG: Final = logging.getLogger(__name__)

#: The periods the console offers. Thirty days is the default because it is the span a
#: monthly delivery cycle fits into, so a user with one delivery a month still appears.
PERIODS: Final[tuple[int, ...]] = (7, 30, 90, 180)

#: What the console asks for when nobody chooses.
DEFAULT_DAYS: Final[int] = 30

#: Run states that mean the tool did its work end to end.
_COMPLETED: Final[tuple[str, ...]] = ("needs_review", "finalized")


@dataclass(frozen=True, slots=True)
class DayCount:
    """How many runs somebody submitted on one day."""

    day: dt.date
    count: int


@dataclass(frozen=True, slots=True)
class UserUsage:
    """One person's use of the tool over a period.

    Attributes:
        user_id: The account.
        name: What to show. Their name, or their username where they have no name.
        username: The sign-in name, so two people called the same thing are distinct.
        roles: Which of ``user``, ``reviewer`` and ``admin`` they hold (ADR-049).
        is_active: Whether the account can still sign in. Deactivated accounts still
            appear, because what they did does not stop having happened (ADR-022).
        runs: Everything they submitted in the period, whatever became of it.
        finalized: Reviewed and signed off.
        needs_review: Finished and waiting for a person.
        failed: The pipeline raised.
        held: The artifacts disagreed with the form and nobody has accepted it yet.
        cancelled: Withdrawn during the grace window, before any work was done.
        in_flight: Queued or running when the report was built.
        orders: Distinct order numbers — how much work, rather than how many attempts.
        customers: Distinct customers, for the spread.
        configurations: Distinct configuration ids.
        repeat_runs: ``runs − orders``: how often an order came back for another go.
        mismatch_runs: Runs that recorded at least one artifact disagreement, whether
            or not it was later accepted.
        tokens: Tokens their runs actually sent, across calls the cache did not
            serve. Counted here for the first time in 6.21d: this report has always
            counted runs and never what they cost.
        cost: Those tokens at the configured rate, or ``0.0`` when nobody has set
            one — in which case the console shows tokens and no currency.
        cached_calls: Calls the cache served, which cost nothing. Shown apart
            rather than folded in, because folding them in flatters the total.
        high_findings: High-severity findings across their completed runs.
        completed_runs: Runs that produced findings at all, which is what
            `high_per_run` divides by.
        first_run_at: Their earliest run in the period.
        last_run_at: Their latest, so an administrator can see who has stopped.
        per_day: One entry per day they submitted anything. Sparse: a day with no runs
            is absent rather than zero, because a 180-day period is mostly zeroes.
    """

    user_id: int
    name: str
    username: str
    roles: tuple[str, ...]
    is_active: bool
    runs: int
    finalized: int
    needs_review: int
    failed: int
    held: int
    cancelled: int
    in_flight: int
    orders: int
    customers: int
    configurations: int
    repeat_runs: int
    mismatch_runs: int
    tokens: int
    cost: float
    cached_calls: int
    high_findings: int
    completed_runs: int
    first_run_at: dt.datetime | None
    last_run_at: dt.datetime | None
    per_day: tuple[DayCount, ...] = field(default=())

    @property
    def failure_rate(self) -> float:
        """How often the pipeline raised on their runs.

        Returns:
            Failed over total, to four places. Zero when they submitted nothing.
        """
        return round(self.failed / self.runs, 4) if self.runs else 0.0

    @property
    def held_rate(self) -> float:
        """How often what they uploaded disagreed with what they typed.

        Returns:
            Held over total, to four places. The most teachable of the three
            measures — a person, not the tool, chooses the files.
        """
        return round(self.held / self.runs, 4) if self.runs else 0.0

    @property
    def repeat_rate(self) -> float:
        """How often an order came back for another attempt.

        Returns:
            Repeats over total, to four places.
        """
        return round(self.repeat_runs / self.runs, 4) if self.runs else 0.0

    @property
    def high_per_run(self) -> float:
        """High-severity findings per completed run.

        Returns:
            The mean, to two places. Counted over completed runs only: a run that
            failed produced no findings and would otherwise drag the average down.
        """
        return round(self.high_findings / self.completed_runs, 2) if self.completed_runs else 0.0


@dataclass(frozen=True, slots=True)
class UsagePeriod:
    """Everyone's use of the tool over one period.

    Attributes:
        start: First day counted, inclusive.
        end: Last day counted, inclusive.
        days: The span, as the console asked for it.
        users: One row per person who submitted anything, busiest first.
        runs: Every run in the period, including those by accounts since removed.
        failure_rate: The deployment's own average, which is what a person's rate is
            worth comparing against.
        held_rate: The same, for artifact disagreements.
        repeat_rate: The same, for orders that came back.
    """

    start: dt.date
    end: dt.date
    days: int
    users: tuple[UserUsage, ...]
    runs: int
    failure_rate: float
    held_rate: float
    repeat_rate: float


def _bounds(days: int, today: dt.date) -> tuple[dt.datetime, dt.datetime, dt.date]:
    """The UTC instants a period of ``days`` ending today covers.

    Args:
        days: How many days back to count, including today.
        today: The last day, inclusive.

    Returns:
        The lower bound, the upper bound, and the first day counted.
    """
    start = today - dt.timedelta(days=days - 1)
    lower = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
    upper = dt.datetime.combine(today, dt.time.max, tzinfo=dt.timezone.utc)
    return lower, upper, start


def build(session: Session, days: int = DEFAULT_DAYS, today: dt.date | None = None) -> UsagePeriod:
    """Count what each person did over the last ``days`` days.

    Args:
        session: An open session.
        days: The period, which the caller has already checked is one of `PERIODS`.
        today: The last day counted. Defaults to today in UTC, which is the frame run
            timestamps are stored in — taking it from a local clock counts the wrong
            day for anybody west of Greenwich in the evening.

    Returns:
        One row per person who submitted something, busiest first, with the
        deployment's own averages beside them.
    """
    last_day = today or dt.datetime.now(dt.timezone.utc).date()
    lower, upper, start = _bounds(days, last_day)

    runs = list(
        session.execute(
            sa.select(models.Run).where(
                models.Run.created_at >= lower,
                models.Run.created_at <= upper,
            )
        ).scalars()
    )
    if not runs:
        return UsagePeriod(
            start=start,
            end=last_day,
            days=days,
            users=(),
            runs=0,
            failure_rate=0.0,
            held_rate=0.0,
            repeat_rate=0.0,
        )

    run_ids = [run.id for run in runs]
    mismatched = _runs_with_a_mismatch(session, run_ids)
    highs = _high_findings_by_run(session, run_ids)
    spent = spend.spend_for_runs(session, run_ids, spend.rate_for(session))

    by_user: dict[int, list[models.Run]] = {}
    for run in runs:
        if run.user_id is not None:
            by_user.setdefault(run.user_id, []).append(run)

    rows = [
        _one_user(session, user_id, theirs, mismatched, highs, spent)
        for user_id, theirs in by_user.items()
    ]
    # Busiest first: an administrator reading top-down is reading in the order the
    # numbers matter, and a rate over three runs is noise whatever it says.
    rows.sort(key=lambda row: (row.runs, row.last_run_at or dt.datetime.min), reverse=True)

    total_orders = len({str(r.order_number).strip() for r in runs if str(r.order_number).strip()})
    _LOG.info("usage by user: %d runs by %d people over %d days", len(runs), len(rows), days)
    return UsagePeriod(
        start=start,
        end=last_day,
        days=days,
        users=tuple(rows),
        runs=len(runs),
        failure_rate=round(sum(1 for r in runs if r.status == "failed") / len(runs), 4),
        held_rate=round(sum(1 for r in runs if r.status == "held") / len(runs), 4),
        repeat_rate=round(max(0, len(runs) - total_orders) / len(runs), 4),
    )


def _runs_with_a_mismatch(session: Session, run_ids: Sequence[int]) -> set[int]:
    """Which runs recorded an artifact disagreement.

    Args:
        session: An open session.
        run_ids: The runs in the period.

    Returns:
        The ids that have at least one mismatch row, accepted or not.
    """
    if not run_ids:
        return set()
    return {
        int(row)
        for row in session.execute(
            sa.select(models.ArtifactMismatch.run_id)
            .where(models.ArtifactMismatch.run_id.in_(run_ids))
            .distinct()
        ).scalars()
    }


def _high_findings_by_run(session: Session, run_ids: Sequence[int]) -> dict[int, int]:
    """How many high-severity findings each run produced.

    Args:
        session: An open session.
        run_ids: The runs in the period.

    Returns:
        Run id to count, absent where a run produced none.
    """
    if not run_ids:
        return {}
    rows = session.execute(
        sa.select(models.Finding.run_id, sa.func.count())
        .where(models.Finding.run_id.in_(run_ids), models.Finding.severity == "high")
        .group_by(models.Finding.run_id)
    ).all()
    return {int(run_id): int(count) for run_id, count in rows}


def _one_user(
    session: Session,
    user_id: int,
    theirs: Sequence[models.Run],
    mismatched: set[int],
    highs: dict[int, int],
    spent: dict[int, "spend.Spend"],
) -> UserUsage:
    """Count one person's runs.

    Args:
        session: An open session.
        user_id: Their account.
        theirs: Their runs in the period.
        mismatched: Run ids that recorded an artifact disagreement.
        highs: High-severity finding counts by run id.
        spent: What each run spent, by run id.

    Returns:
        Their row.
    """
    account = session.get(models.User, user_id)
    statuses = [run.status for run in theirs]
    orders = {str(r.order_number).strip() for r in theirs if str(r.order_number).strip()}
    completed = [r for r in theirs if r.status in _COMPLETED]

    per_day: dict[dt.date, int] = {}
    for run in theirs:
        day = run.created_at.date()
        per_day[day] = per_day.get(day, 0) + 1

    created = [run.created_at for run in theirs]
    return UserUsage(
        user_id=user_id,
        name=(account.name or account.username) if account is not None else f"account {user_id}",
        username=account.username if account is not None else "",
        roles=tuple(account.roles or ()) if account is not None else (),
        is_active=account.is_active if account is not None else False,
        runs=len(theirs),
        finalized=statuses.count("finalized"),
        needs_review=statuses.count("needs_review"),
        failed=statuses.count("failed"),
        held=statuses.count("held"),
        cancelled=statuses.count("cancelled"),
        in_flight=statuses.count("queued") + statuses.count("running"),
        orders=len(orders),
        customers=len(
            {str(r.customer_name).strip() for r in theirs if str(r.customer_name).strip()}
        ),
        configurations=len(
            {str(r.configuration_id).strip() for r in theirs if str(r.configuration_id).strip()}
        ),
        repeat_runs=max(0, len(theirs) - len(orders)),
        mismatch_runs=sum(1 for r in theirs if r.id in mismatched),
        tokens=sum(spent[r.id].tokens for r in theirs if r.id in spent),
        cost=sum(spent[r.id].cost for r in theirs if r.id in spent),
        cached_calls=sum(spent[r.id].cached_calls for r in theirs if r.id in spent),
        high_findings=sum(highs.get(r.id, 0) for r in completed),
        completed_runs=len(completed),
        first_run_at=min(created) if created else None,
        last_run_at=max(created) if created else None,
        per_day=tuple(DayCount(day=d, count=c) for d, c in sorted(per_day.items())),
    )
