"""What the tool has displaced, over a period somebody chooses (Phase 6.16).

An administrator is asked, periodically, what the tool has been worth. The numbers to
answer that are already in the run tables; what has been missing is the arithmetic and
somewhere to put it.

**Unique orders, not runs.** An order checked three times — a re-run after a fix, a
clone with a correction — displaced one manual check, not three. Counting runs would
flatter the number, and a figure that flatters is a figure nobody outside the team will
believe. This counts distinct order numbers.

**The hours figure is the administrator's, not the tool's.** The tool does not know how
long a manual check takes; somebody sets it (``value.hours_per_order``, four by
default). The report says which number was used and that it was supplied, so a reader
can disagree with the assumption rather than with the arithmetic. A report that hid its
assumption would be worth less, not more.

**Finalized runs only.** A run that failed, was cancelled, or is still waiting for a
reviewer has not displaced anything yet.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models

__all__ = ["ValueReport", "build"]

_LOG: Final = logging.getLogger(__name__)

#: Run states that represent work the tool actually did end to end.
_COUNTED: Final[tuple[str, ...]] = ("finalized",)


@dataclass(frozen=True, slots=True)
class ValueReport:
    """What the tool displaced between two dates.

    Attributes:
        start: First day counted, inclusive.
        end: Last day counted, inclusive.
        runs: Finalized runs in the period, including repeats of one order.
        orders: Distinct order numbers among them — what the hours are based on.
        customers: Distinct customers, for context on the spread.
        hours_per_order: The figure an administrator supplied.
        hours_saved: ``orders × hours_per_order``.
        repeat_runs: ``runs − orders``: how many were a second look at an order
            already counted. Shown so the difference between the two is visible
            rather than quietly absorbed.
    """

    start: dt.date
    end: dt.date
    runs: int
    orders: int
    customers: int
    hours_per_order: int
    hours_saved: int
    repeat_runs: int

    @property
    def days(self) -> int:
        """How many days the period covers, inclusive.

        Returns:
            The span in days, at least one.
        """
        return max(1, (self.end - self.start).days + 1)

    @property
    def working_weeks(self) -> float:
        """The hours saved expressed in 37.5-hour weeks.

        Returns:
            Weeks to one decimal place. A round number of hours means little to a
            reader; weeks of somebody's time means something.
        """
        return round(self.hours_saved / 37.5, 1)


def build(session: Session, start: dt.date, end: dt.date, hours_per_order: int) -> ValueReport:
    """Count what the tool displaced between two dates.

    Args:
        session: An open session.
        start: First day to count, inclusive.
        end: Last day to count, inclusive.
        hours_per_order: What one manual check is taken to cost, in hours.

    Returns:
        The report. Every number is counted by code from the run records; nothing here
        is estimated except the hours figure, which was supplied.
    """
    # Inclusive of the end date: somebody asking for "the 1st to the 30th" means the
    # 30th, and an exclusive bound would quietly drop a day's work from the total.
    upper = dt.datetime.combine(end, dt.time.max, tzinfo=dt.timezone.utc)
    lower = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)

    rows = list(
        session.execute(
            sa.select(models.Run.order_number, models.Run.customer_name).where(
                models.Run.status.in_(_COUNTED),
                models.Run.created_at >= lower,
                models.Run.created_at <= upper,
            )
        ).all()
    )

    orders = {str(order).strip() for order, _ in rows if str(order).strip()}
    customers = {str(customer).strip() for _, customer in rows if str(customer).strip()}
    hours = len(orders) * max(0, hours_per_order)

    _LOG.info(
        "value report %s..%s: %d runs, %d orders, %d hours",
        start,
        end,
        len(rows),
        len(orders),
        hours,
    )
    return ValueReport(
        start=start,
        end=end,
        runs=len(rows),
        orders=len(orders),
        customers=len(customers),
        hours_per_order=hours_per_order,
        hours_saved=hours,
        repeat_runs=max(0, len(rows) - len(orders)),
    )
