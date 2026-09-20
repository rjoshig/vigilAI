"""Scheduled banners, and the rules that keep them worth reading (Phase 6.14g).

An administrator needs to say "maintenance starts at 11pm on the 6th" to whoever is
using the app when it matters. The tool cannot know it, nobody should have to deploy to
say it, and an email is read by whoever happens to open it.

Three constraints do the real work here, and each exists because of the way banners
usually fail:

- **Every notice has an end.** A banner nobody remembers to take down is how an app
  comes to carry a stale warning for a month, and a stale warning teaches people to
  stop reading banners at all. The end date is not optional.
- **At most five are scheduled at once.** Not a storage limit — a reading limit. Two
  banners are read; five are skimmed; ten are wallpaper.
- **None of them is dismissible.** A notice somebody scheduled is a notice they wanted
  seen, and a dismiss button turns "read this" into "click this".

Everything here is code: what shows is a function of the clock and the stored rows, and
no model is involved in any of it.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Final, Literal, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db import models
from greenlight_ai.db.types import utcnow

__all__ = [
    "AUDIENCES",
    "Audience",
    "LEVELS",
    "Level",
    "MAX_ACTIVE",
    "MAX_MESSAGE_CHARS",
    "AnnouncementError",
    "showing_now",
    "validate",
]

_LOG: Final = logging.getLogger(__name__)

Level = Literal["info", "warning", "critical"]
Audience = Literal["user", "admin", "both"]

#: How serious the notice is, in the order the screens offer them.
LEVELS: Final[tuple[str, ...]] = ("info", "warning", "critical")

#: Which app sees it. Most messages are for one audience, not both.
AUDIENCES: Final[tuple[str, ...]] = ("user", "admin", "both")

#: How many may be scheduled at once. A reading limit, not a storage one.
MAX_ACTIVE: Final[int] = 5

#: Long enough for a paragraph explaining a change and where to go with questions,
#: short enough that nobody writes a release note at the top of the app.
MAX_MESSAGE_CHARS: Final[int] = 2000


class AnnouncementError(Exception):
    """A notice cannot be scheduled as written. The message says why."""


def validate(
    session: Session,
    message: str,
    level: str,
    audience: str,
    starts_at: dt.datetime,
    ends_at: dt.datetime,
    exclude_id: int | None = None,
) -> None:
    """Check a notice before it is stored.

    Args:
        session: An open session, for the count of what is already scheduled.
        message: The text.
        level: One of :data:`LEVELS`.
        audience: One of :data:`AUDIENCES`.
        starts_at: When it begins showing.
        ends_at: When it stops.
        exclude_id: A row being edited, which should not count against the limit.

    Raises:
        AnnouncementError: When the text is empty or too long, the level or audience
            is not one the apps render, the window ends before it starts, or five are
            already scheduled.
    """
    text = message.strip()
    if not text:
        raise AnnouncementError("a notice with no message would show an empty bar")
    if len(text) > MAX_MESSAGE_CHARS:
        raise AnnouncementError(
            f"the message is {len(text)} characters; the limit is {MAX_MESSAGE_CHARS}"
        )
    if level not in LEVELS:
        raise AnnouncementError(f"level must be one of {', '.join(LEVELS)}; got {level!r}")
    if audience not in AUDIENCES:
        raise AnnouncementError(f"audience must be one of {', '.join(AUDIENCES)}; got {audience!r}")
    if ends_at <= starts_at:
        raise AnnouncementError("the notice would end before it started")

    statement = (
        sa.select(sa.func.count())
        .select_from(models.Announcement)
        .where(
            models.Announcement.is_active.is_(True),
            models.Announcement.ends_at > utcnow(),
        )
    )
    if exclude_id is not None:
        statement = statement.where(models.Announcement.id != exclude_id)
    scheduled = int(session.execute(statement).scalar_one())
    if scheduled >= MAX_ACTIVE:
        raise AnnouncementError(
            f"{scheduled} notices are already scheduled, which is the limit of "
            f"{MAX_ACTIVE}. Two banners are read and five are skimmed; switch one off "
            "or let it expire before adding another."
        )


def showing_now(
    session: Session, audience: str, now: dt.datetime | None = None
) -> Sequence[models.Announcement]:
    """The notices an app should be showing at this moment.

    Args:
        session: An open session.
        audience: ``user`` or ``admin``; a notice for ``both`` matches either.
        now: The moment to ask about, injectable so a test does not wait.

    Returns:
        The notices in force, most serious first and then oldest first — so a critical
        notice is never pushed below an informational one that happens to be newer.
    """
    moment = now or utcnow()
    rows = list(
        session.execute(
            sa.select(models.Announcement).where(
                models.Announcement.is_active.is_(True),
                models.Announcement.starts_at <= moment,
                models.Announcement.ends_at > moment,
                models.Announcement.audience.in_([audience, "both"]),
            )
        ).scalars()
    )
    order = {level: index for index, level in enumerate(reversed(LEVELS))}
    rows.sort(key=lambda row: (order.get(row.level, len(LEVELS)), row.id))
    if rows:
        _LOG.debug("%d notice(s) showing for %s", len(rows), audience)
    return rows
