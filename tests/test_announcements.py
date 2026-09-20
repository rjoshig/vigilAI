"""Scheduled banners, and the three rules that keep them worth reading (6.14g).

The rules under test are not arbitrary limits. Each is there because of a way banners
fail in practice: one with no end date becomes a stale warning nobody reads, and five at
once are skimmed rather than read. What shows is a function of the clock and the stored
rows; no model is involved.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai import announcements as an
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory against a fresh SQLite file (ADR-017)."""
    engine = create_engine(
        DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'notices.db'}", data_dir=tmp_path)
    )
    create_all(engine)
    return session_factory(engine)


def _add(
    session: Session,
    message: str = "Maintenance at 11pm.",
    level: str = "info",
    audience: str = "both",
    starts: dt.datetime | None = None,
    ends: dt.datetime | None = None,
    active: bool = True,
) -> models.Announcement:
    """Store a notice directly, so the tests are about the rules and not the API."""
    row = models.Announcement(
        level=level,
        audience=audience,
        message=message,
        starts_at=starts or NOW - dt.timedelta(hours=1),
        ends_at=ends or NOW + dt.timedelta(hours=1),
        is_active=active,
    )
    session.add(row)
    session.flush()
    return row


class TestWhatIsShowing:
    """The clock decides, and nothing else."""

    def test_a_notice_inside_its_window_shows(self, factory: sessionmaker[Session]) -> None:
        """The ordinary case."""
        with factory() as session:
            _add(session)
            assert len(an.showing_now(session, "user", NOW)) == 1

    def test_a_notice_before_its_window_does_not(self, factory: sessionmaker[Session]) -> None:
        """Scheduling it tomorrow means tomorrow."""
        with factory() as session:
            _add(session, starts=NOW + dt.timedelta(days=1), ends=NOW + dt.timedelta(days=2))
            assert an.showing_now(session, "user", NOW) == []

    def test_a_notice_past_its_window_takes_itself_down(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The whole reason the end date is required."""
        with factory() as session:
            _add(session, starts=NOW - dt.timedelta(days=2), ends=NOW - dt.timedelta(days=1))
            assert an.showing_now(session, "user", NOW) == []

    def test_switching_one_off_hides_it_without_losing_it(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A recurring message is switched back on rather than retyped."""
        with factory() as session:
            _add(session, active=False)
            assert an.showing_now(session, "user", NOW) == []

    def test_an_audience_only_sees_its_own(self, factory: sessionmaker[Session]) -> None:
        """Most messages are for one app, not both."""
        with factory() as session:
            _add(session, message="for users", audience="user")
            _add(session, message="for admins", audience="admin")
            _add(session, message="for everyone", audience="both")

            users = [row.message for row in an.showing_now(session, "user", NOW)]
            admins = [row.message for row in an.showing_now(session, "admin", NOW)]
        assert users == ["for users", "for everyone"]
        assert admins == ["for admins", "for everyone"]

    def test_the_most_serious_notice_is_first(self, factory: sessionmaker[Session]) -> None:
        """A critical notice is never pushed below an informational newer one."""
        with factory() as session:
            _add(session, message="fyi", level="info")
            _add(session, message="down at 11", level="critical")
            _add(session, message="careful", level="warning")
            order = [row.level for row in an.showing_now(session, "user", NOW)]
        assert order == ["critical", "warning", "info"]


class TestTheRules:
    """What cannot be scheduled, and why."""

    def test_an_empty_message_is_refused(self, factory: sessionmaker[Session]) -> None:
        """It would render an empty bar."""
        with factory() as session:
            with pytest.raises(an.AnnouncementError, match="no message"):
                an.validate(session, "   ", "info", "both", NOW, NOW + dt.timedelta(hours=1))

    def test_a_message_past_the_limit_is_refused(self, factory: sessionmaker[Session]) -> None:
        """Long enough for a paragraph, not for a release note."""
        with factory() as session:
            with pytest.raises(an.AnnouncementError, match="limit is 2000"):
                an.validate(
                    session,
                    "x" * (an.MAX_MESSAGE_CHARS + 1),
                    "info",
                    "both",
                    NOW,
                    NOW + dt.timedelta(hours=1),
                )

    def test_a_window_that_ends_before_it_starts_is_refused(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A typo in the dates should not store a notice that can never show."""
        with factory() as session:
            with pytest.raises(an.AnnouncementError, match="before it started"):
                an.validate(session, "hello", "info", "both", NOW, NOW - dt.timedelta(hours=1))

    @pytest.mark.parametrize("level", ["urgent", "", "INFO "])
    def test_an_unknown_level_is_refused(self, factory: sessionmaker[Session], level: str) -> None:
        """The apps render three, so three is what can be stored."""
        with factory() as session:
            with pytest.raises(an.AnnouncementError, match="level must be"):
                an.validate(session, "hello", level, "both", NOW, NOW + dt.timedelta(hours=1))

    def test_a_sixth_notice_is_refused_with_the_reason(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A reading limit, not a storage one, and the message says so."""
        with factory() as session:
            for index in range(an.MAX_ACTIVE):
                _add(session, message=f"notice {index}")
            with pytest.raises(an.AnnouncementError, match="skimmed"):
                an.validate(session, "one more", "info", "both", NOW, NOW + dt.timedelta(days=1))

    def test_an_expired_notice_does_not_count_against_the_limit(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Otherwise the limit would fill up permanently after five messages."""
        with factory() as session:
            for index in range(an.MAX_ACTIVE):
                _add(
                    session,
                    message=f"old {index}",
                    starts=NOW - dt.timedelta(days=9),
                    ends=NOW - dt.timedelta(days=8),
                )
            an.validate(session, "a new one", "info", "both", NOW, NOW + dt.timedelta(days=1))

    def test_editing_a_notice_does_not_count_itself(self, factory: sessionmaker[Session]) -> None:
        """Otherwise the fifth notice could never be edited."""
        with factory() as session:
            rows = [_add(session, message=f"notice {i}") for i in range(an.MAX_ACTIVE)]
            an.validate(
                session,
                "edited",
                "warning",
                "both",
                NOW,
                NOW + dt.timedelta(days=1),
                exclude_id=rows[0].id,
            )
