"""Counting administrators without asking the database about JSON (ADR-017, ADR-049).

*Is there another administrator?* used to be a SQL predicate on the single ``role``
column. The role list that replaced it is JSON, and JSON containment is spelled
differently on SQLite and on Postgres, so the question moved into Python over what is
the smallest table in the schema. These tests pin the answer rather than the dialect.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from greenlight_ai.auth.accounts import (
    ensure_bootstrap,
    ensure_placeholder,
    other_active_admins,
)
from greenlight_ai.auth.settings import BOOTSTRAP_USERNAME
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings


@pytest.fixture()
def session(tmp_path: Path) -> Iterator[Session]:
    """An open session against a fresh SQLite file.

    Yields:
        The session, closed when the test ends.
    """
    engine = create_engine(
        DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'admins.db'}", data_dir=tmp_path)
    )
    create_all(engine)
    with session_factory(engine)() as open_session:
        yield open_session


def _account(session: Session, username: str, roles: list[str], active: bool = True) -> models.User:
    """Add an account holding exactly these roles.

    Args:
        session: An open session.
        username: What it signs in as.
        roles: What it holds.
        active: Whether it is usable.

    Returns:
        The row.
    """
    row = models.User(
        username=username,
        name=username,
        email=f"{username}@localhost",
        password_hash="x",
        roles=roles,
        is_active=active,
    )
    session.add(row)
    session.flush()
    return row


def test_the_bootstrap_admin_is_created_once(session: Session) -> None:
    """A second call finds the first through its role list, not through ``role``."""
    first = ensure_bootstrap(session)

    assert first is not None and first.username == BOOTSTRAP_USERNAME
    assert ensure_bootstrap(session) is None


def test_an_unknown_stored_role_is_dropped_rather_than_trusted(session: Session) -> None:
    """A name that is not a role reads as a plain user, so it cannot buy admin access."""
    real = _account(session, "one", ["admin"])
    _account(session, "two", ["superuser"])

    assert other_active_admins(session, besides=real.id) == 0


def test_the_placeholder_is_never_the_administrator_that_exists(session: Session) -> None:
    """It holds ``admin`` but cannot sign in, so a fresh install still needs a way in."""
    ensure_placeholder(session)

    assert ensure_bootstrap(session) is not None


def test_the_last_administrator_has_nobody_behind_them(session: Session) -> None:
    """Zero is what the users router refuses on."""
    only = _account(session, "one", ["user", "admin"])

    assert other_active_admins(session, besides=only.id) == 0


def test_a_second_administrator_is_counted(session: Session) -> None:
    """With two, either may be demoted."""
    first = _account(session, "one", ["user", "admin"])
    _account(session, "two", ["admin"])

    assert other_active_admins(session, besides=first.id) == 1


def test_a_deactivated_administrator_does_not_count(session: Session) -> None:
    """Somebody who cannot sign in cannot unlock the console for anybody."""
    first = _account(session, "one", ["admin"])
    _account(session, "two", ["admin"], active=False)

    assert other_active_admins(session, besides=first.id) == 0


def test_a_reviewer_does_not_count_as_an_administrator(session: Session) -> None:
    """The whole point of the third role: a reviewer cannot reach the Users screen."""
    first = _account(session, "one", ["admin"])
    _account(session, "two", ["user", "reviewer"])

    assert other_active_admins(session, besides=first.id) == 0
