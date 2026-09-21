"""The account everything is attributed to while login is off (ADR-022, ADR-049).

It holds **user and admin**. While login is off it is the only account there is and it
can already do everything — `deps.py` hands it `is_admin=True` — so the stored roles say
what the behaviour already is. The failure this guards against is the quiet one: the
console starts gating on roles and refuses the only account anybody has.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from greenlight_ai.auth.accounts import ensure_placeholder
from greenlight_ai.auth.roles import Capability, capabilities_of, has_capability
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    """An open session against a fresh SQLite file (ADR-017).

    Yields:
        The session, closed when the test ends.
    """
    engine = create_engine(
        DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'accounts.db'}", data_dir=tmp_path)
    )
    create_all(engine)
    with session_factory(engine)() as open_session:
        yield open_session


def test_the_placeholder_is_a_user_and_an_administrator(session: Session) -> None:
    """Both, because while login is off it behaves as both."""
    row = ensure_placeholder(session)

    assert list(row.roles) == ["user", "admin"]
    assert row.role == "admin", "the legacy field holds the strongest role held"


def test_the_placeholder_may_do_everything_in_the_console(session: Session) -> None:
    """The point of the change: gating on roles must not lock out the only account."""
    row = ensure_placeholder(session)

    assert capabilities_of(row.roles) == frozenset(Capability)
    assert has_capability(row.roles, Capability.MANAGE_SETTINGS)


def test_it_still_cannot_be_signed_in_as(session: Session) -> None:
    """Being an administrator on paper must not make it an account somebody can use."""
    row = ensure_placeholder(session)

    assert row.password_hash == ""
    assert row.is_placeholder is True


def test_seeding_twice_does_not_make_a_second_one(session: Session) -> None:
    """It is fetched, not recreated, so its roles are not reset under a running app."""
    first = ensure_placeholder(session)
    first.roles = ["user"]
    session.flush()

    again = ensure_placeholder(session)

    assert again.id == first.id
    assert list(again.roles) == ["user"], "an existing row is returned untouched"
