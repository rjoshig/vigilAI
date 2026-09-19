"""The rule lifecycle (ADR-021).

No rule expires on its own, deletion is soft for six months, and every move is
recorded with who made it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.training import lifecycle


@pytest.fixture()
def session(tmp_path: Path):
    """One open session against a fresh database."""
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'l.db'}"))
    create_all(engine)
    factory: sessionmaker[Session] = session_factory(engine)
    with factory() as open_session:
        yield open_session


@pytest.fixture()
def rule(session: Session) -> models.FieldConstraint:
    """An active field constraint to move around."""
    row = models.FieldConstraint(
        field="account_status", constraint="not_blank", value={}, state="active"
    )
    session.add(row)
    session.flush()
    return row


def test_disabling_is_reversible_and_recorded(
    session: Session, rule: models.FieldConstraint
) -> None:
    """A noisy rule goes here rather than being deleted, which keeps the argument for it."""
    lifecycle.disable_rule(session, "field_constraint", rule.id, actor="Dana")
    assert rule.state == "disabled"

    lifecycle.enable_rule(session, "field_constraint", rule.id, actor="Dana")
    assert rule.state == "active"

    changes = list(session.execute(sa.select(models.RuleStateChange)).scalars())
    assert [(c.from_state, c.to_state) for c in changes] == [
        ("active", "disabled"),
        ("disabled", "active"),
    ]
    assert {c.actor for c in changes} == {"Dana"}


def test_a_deleted_rule_stops_running_at_once(
    session: Session, rule: models.FieldConstraint
) -> None:
    """Soft, but immediate."""
    lifecycle.delete_rule(session, "field_constraint", rule.id, actor="Dana")
    assert rule.state == "deleted"
    assert rule.deleted_at is not None
    assert rule.state not in lifecycle.RUNNING_STATES


def test_a_deletion_can_be_undone_for_six_months(
    session: Session, rule: models.FieldConstraint
) -> None:
    """It comes back switched off: whoever deleted it had a reason worth reading."""
    lifecycle.delete_rule(session, "field_constraint", rule.id, actor="Dana")
    rule.deleted_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=150)
    session.flush()

    lifecycle.restore_rule(session, "field_constraint", rule.id, actor="Dana")
    assert rule.state == "disabled"
    assert rule.deleted_at is None


def test_a_deletion_older_than_the_window_cannot_be_undone(
    session: Session, rule: models.FieldConstraint
) -> None:
    """After six months it is permanent, and the message says so."""
    lifecycle.delete_rule(session, "field_constraint", rule.id, actor="Dana")
    rule.deleted_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=200)
    session.flush()

    with pytest.raises(lifecycle.LifecycleError, match="no longer be restored"):
        lifecycle.restore_rule(session, "field_constraint", rule.id, actor="Dana")


def test_purging_keeps_a_tombstone(session: Session) -> None:
    """A finding on an old run cites a rule by reference, and a reference to
    nothing explains nothing."""
    row = models.CheckDefinitionRow(
        name="old", expression="1 == 1", reasoning="because", state="deleted"
    )
    row.deleted_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=200)
    session.add(row)
    session.flush()

    assert lifecycle.purge_deleted_rules(session) == 1
    assert row.expression == ""
    assert row.name == "old"
    assert row.reasoning == "because"


def test_nothing_expires_on_its_own(session: Session, rule: models.FieldConstraint) -> None:
    """A rule unfired for a year is either load-bearing or dead, and only a person
    can tell which."""
    rule.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=900)
    session.flush()
    assert lifecycle.purge_deleted_rules(session) == 0
    assert rule.state == "active"


def test_the_switch_and_the_state_are_kept_consistent(session: Session) -> None:
    """Two fields that can disagree is a bug waiting to be found in production."""
    row = models.CheckDefinitionRow(name="c", expression="1 == 1", is_active=True)
    session.add(row)
    session.flush()

    lifecycle.disable_rule(session, "check", row.id, actor="Dana")
    assert (row.state, row.is_active) == ("disabled", False)

    lifecycle.enable_rule(session, "check", row.id, actor="Dana")
    assert (row.state, row.is_active) == ("active", True)
