"""Tests for the artifact-type and scope catalog (ADR-020).

The two rules the catalog promises are the two things worth pinning down: an empty
table means "use the defaults", and seeding twice adds nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import catalog, models
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    """A session factory against a fresh, empty SQLite file.

    Args:
        tmp_path: pytest's per-test directory.

    Returns:
        The factory.
    """
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'c.db'}"))
    create_all(engine)
    return session_factory(engine)


def test_empty_database_falls_back_to_the_shipped_defaults(
    factory: sessionmaker[Session],
) -> None:
    """A fresh install accepts the same inputs it did before any of this existed."""
    with factory() as session:
        artifacts = catalog.load_artifacts(session)
        scopes = catalog.load_scopes(session)

    assert [a.key for a in artifacts] == [a.key for a in catalog.DEFAULT_ARTIFACTS]
    assert [s.code for s in scopes] == ["AM", "AS", "ARCHIVE", "OTHER"]
    assert all(s.standing_instructions == "" for s in scopes)


def test_active_only_hides_the_types_that_ship_switched_off(
    factory: sessionmaker[Session],
) -> None:
    """Score distribution and cross tab ship inactive, so they are not offered."""
    with factory() as session:
        keys = catalog.active_report_keys(session)

    assert "dirt" in keys
    assert "score_distribution" not in keys
    assert "osl" not in keys and "config" not in keys


def test_seeding_is_idempotent_and_preserves_edits(factory: sessionmaker[Session]) -> None:
    """A second seed adds nothing and overwrites nothing an administrator changed."""
    with factory() as session:
        first = catalog.seed_defaults(session)
        session.commit()

    assert first == len(catalog.DEFAULT_ARTIFACTS) + len(catalog.DEFAULT_SCOPES)

    with factory() as session:
        row = session.execute(
            sa.select(models.ArtifactType).where(models.ArtifactType.key == "dirt")
        ).scalar_one()
        row.ai_context = "Watch the masked sample tab."
        row.is_active = False
        session.commit()

    with factory() as session:
        assert catalog.seed_defaults(session) == 0
        session.commit()
        row = session.execute(
            sa.select(models.ArtifactType).where(models.ArtifactType.key == "dirt")
        ).scalar_one()
        assert row.ai_context == "Watch the masked sample tab."
        assert row.is_active is False
        assert "dirt" not in catalog.active_report_keys(session)


def test_an_admin_defined_type_joins_the_upload_slots(factory: sessionmaker[Session]) -> None:
    """A new report type needs no code change to be accepted."""
    with factory() as session:
        catalog.seed_defaults(session)
        session.add(
            models.ArtifactType(
                key="tradeline_mix",
                label="Tradeline mix",
                kind="report",
                is_builtin=False,
                sort_order=95,
            )
        )
        session.commit()
        assert "tradeline_mix" in catalog.active_report_keys(session)


def test_scope_lookup_tolerates_a_run_naming_none_or_a_deleted_one(
    factory: sessionmaker[Session],
) -> None:
    """A missing scope means no extra context, not a failed run."""
    with factory() as session:
        catalog.seed_defaults(session)
        session.commit()
        assert catalog.scope_for(session, "") is None
        assert catalog.scope_for(session, "GONE") is None
        found = catalog.scope_for(session, "AM")
        assert found is not None and found.label == "Account Monitoring"
