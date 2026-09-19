"""Tests for runtime settings resolution (ADR-023).

The property that matters most is the negative one: a setting nobody has touched
behaves exactly as it did when the environment was the only source.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config import secrets
from greenlight_ai.config.registry import SETTINGS, SETTINGS_BY_KEY
from greenlight_ai.config.store import (
    clear_setting,
    effective,
    fallback,
    invalidate,
    read_secret,
    resolve,
    write_setting,
)
from greenlight_ai.db import models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory against a fresh, empty SQLite file."""
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 's.db'}"))
    create_all(engine)
    invalidate()
    return session_factory(engine)


@pytest.fixture()
def session(factory: sessionmaker[Session]):
    """One open session, with the override cache cleared around it."""
    with factory() as open_session:
        yield open_session
    invalidate()


def test_an_untouched_setting_comes_from_the_default(session: Session) -> None:
    """A fresh install behaves as it always did."""
    resolved = resolve(session, "llm.max_tokens", {})
    assert resolved.value == 2000
    assert resolved.source == "default"


def test_the_environment_beats_the_default(session: Session) -> None:
    """The middle layer still works, which is what most deployments use."""
    resolved = resolve(session, "llm.max_tokens", {"LLM_MAX_TOKENS": "4096"})
    assert resolved.value == 4096
    assert resolved.source == "env"


def test_the_console_beats_the_environment(session: Session) -> None:
    """The whole point: an administrator's value takes precedence."""
    write_setting(session, "llm.max_tokens", 8000, actor="Dana", environ={})
    resolved = resolve(session, "llm.max_tokens", {"LLM_MAX_TOKENS": "4096"})
    assert resolved.value == 8000
    assert resolved.source == "admin"


def test_reverting_falls_back_to_the_layer_beneath(session: Session) -> None:
    """Revert is a real action, not a guess at what the value used to be."""
    env = {"LLM_MAX_TOKENS": "4096"}
    write_setting(session, "llm.max_tokens", 8000, actor="Dana", environ=env)
    assert fallback("llm.max_tokens", env).value == 4096

    reverted = clear_setting(session, "llm.max_tokens", actor="Dana", environ=env)
    assert reverted.value == 4096
    assert reverted.source == "env"


def test_a_change_is_visible_immediately_in_the_process_that_made_it(
    session: Session,
) -> None:
    """A cache that outlived its own write would make the console feel broken."""
    assert resolve(session, "queue.max_concurrent_runs", {}).value == 4
    write_setting(session, "queue.max_concurrent_runs", 9, actor="Dana", environ={})
    assert resolve(session, "queue.max_concurrent_runs", {}).value == 9


def test_a_read_only_setting_cannot_be_changed(session: Session) -> None:
    """A console that can change how it reaches its own database can lock everyone out."""
    with pytest.raises(ValueError, match="not editable"):
        write_setting(session, "platform.database_url", "sqlite://", actor="Dana", environ={})


def test_an_out_of_range_value_is_refused(session: Session) -> None:
    """Bounds are declared once, in the registry, and enforced on the way in."""
    with pytest.raises(ValueError):
        write_setting(session, "llm.max_tokens", 10, actor="Dana", environ={})


def test_an_unusable_stored_value_falls_back_rather_than_failing(
    session: Session,
) -> None:
    """A malformed value must not take the service down."""
    session.add(models.AppSetting(key="llm.max_tokens", value="not a number"))
    session.flush()
    invalidate()
    assert resolve(session, "llm.max_tokens", {}).value == 2000


def test_every_change_is_recorded_with_its_previous_value(session: Session) -> None:
    """Who changed what, from what, and when."""
    write_setting(session, "retention.days", 30, actor="Dana", environ={})
    write_setting(session, "retention.days", 60, actor="Dana", environ={})
    rows = list(session.query(models.ConfigChange).order_by(models.ConfigChange.id).all())
    assert [(r.old_value, r.new_value) for r in rows] == [(90, 30), (30, 60)]
    assert {r.changed_by for r in rows} == {"Dana"}


# --- secrets ------------------------------------------------------------------------


def test_a_secret_is_never_returned_by_resolution(session: Session) -> None:
    """The console learns that one is set, and nothing more."""
    key = Fernet.generate_key().decode()
    env = {"GREENLIGHT_AI_SECRET_KEY": key}
    write_setting(session, "llm.api_key", "sk-secret-value-9zzz", actor="Dana", environ=env)

    resolved = resolve(session, "llm.api_key", env)
    assert resolved.value == ""
    assert resolved.is_set is True
    assert resolved.last4 == "9zzz"
    assert read_secret(session, "llm.api_key", env) == "sk-secret-value-9zzz"


def test_a_secret_is_stored_encrypted(session: Session) -> None:
    """What is in the table is ciphertext, not the key."""
    env = {"GREENLIGHT_AI_SECRET_KEY": Fernet.generate_key().decode()}
    write_setting(session, "llm.api_key", "sk-plaintext-abcd", actor="Dana", environ=env)
    row = session.query(models.AppSetting).filter_by(key="llm.api_key").one()
    assert "sk-plaintext" not in str(row.value)
    assert row.is_secret is True


def test_a_secret_change_records_that_it_changed_and_nothing_else(
    session: Session,
) -> None:
    """The audit trail must not become the place the secret leaks."""
    env = {"GREENLIGHT_AI_SECRET_KEY": Fernet.generate_key().decode()}
    write_setting(session, "llm.api_key", "sk-plaintext-abcd", actor="Dana", environ=env)
    row = session.query(models.ConfigChange).filter_by(key="llm.api_key").one()
    assert row.new_value == "(secret)"
    assert "sk-plaintext" not in str(row.old_value) + str(row.new_value)


def test_without_a_master_key_a_secret_is_refused_rather_than_stored(
    session: Session,
) -> None:
    """Refusing is better than storing something that only looks protected."""
    with pytest.raises(secrets.SecretsUnavailable):
        write_setting(session, "llm.api_key", "sk-anything", actor="Dana", environ={})


def test_a_secret_falls_back_to_the_environment(session: Session) -> None:
    """A deployment with no master key keeps its key in .env, and that still works."""
    env = {"LLM_API_KEY": "sk-from-the-environment"}
    assert read_secret(session, "llm.api_key", env) == "sk-from-the-environment"
    assert resolve(session, "llm.api_key", env).source == "env"


def test_a_rotated_master_key_still_decrypts(session: Session) -> None:
    """MultiFernet from the first day, so rotation is not a migration under pressure."""
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    write_setting(
        session,
        "llm.api_key",
        "sk-rotate-me",
        actor="Dana",
        environ={"GREENLIGHT_AI_SECRET_KEY": old},
    )
    rotated = {"GREENLIGHT_AI_SECRET_KEY": f"{new},{old}"}
    assert read_secret(session, "llm.api_key", rotated) == "sk-rotate-me"


# --- the registry as a whole --------------------------------------------------------


def test_every_setting_resolves_and_reports_its_layer(session: Session) -> None:
    """The console's read-only view must never have a hole in it."""
    rows = effective(session, {})
    assert len(rows) == len(SETTINGS)
    assert all(row.source in ("admin", "env", "default") for row in rows)
    assert {row.spec.key for row in rows} == set(SETTINGS_BY_KEY)


def test_the_bootstrapping_settings_are_not_editable() -> None:
    """Nothing that is needed to reach the settings store may live inside it."""
    locked = {spec.key for spec in SETTINGS if not spec.editable}
    assert locked == {
        "platform.database_url",
        "platform.data_dir",
        "platform.bind_host",
    }


def test_every_setting_belongs_to_a_listed_group() -> None:
    """The console renders group by group, so a setting in no group is unreachable.

    This is not hypothetical: three training settings were added with a group the
    GROUPS tuple did not list, and the endpoint silently dropped them while every
    other test still passed.
    """
    from greenlight_ai.config.registry import GROUPS

    orphans = {spec.key: spec.group for spec in SETTINGS if spec.group not in GROUPS}
    assert not orphans, f"settings in no listed group: {orphans}"


def test_every_group_holds_at_least_one_setting() -> None:
    """An empty section is a heading with nothing under it."""
    from greenlight_ai.config.registry import GROUPS, group_of

    assert all(group_of(group) for group in GROUPS)
