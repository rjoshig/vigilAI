"""Tests for the models, the portable types, and the repository."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from vigilai.checks.definitions import DEFAULT_CATEGORIES
from vigilai.db import models, repository
from vigilai.db.session import create_all, create_engine, healthcheck, session_factory
from vigilai.db.settings import DEFAULT_URL, DbSettings
from vigilai.parsers.masking import DEFAULT_MASKED_COLUMNS


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'r.db'}"))
    create_all(engine)
    return session_factory(engine)


@pytest.fixture()
def session(factory: sessionmaker[Session]):
    with factory() as s:
        yield s


# --- settings and engine ------------------------------------------------------------


def test_sqlite_is_the_default_backend() -> None:
    assert DbSettings.from_env({}).backend == "sqlite"
    assert DEFAULT_URL.startswith("sqlite")


def test_postgres_is_one_setting_away() -> None:
    settings = DbSettings.from_env({"DATABASE_URL": "postgresql+psycopg://u:p@h/db"})
    assert settings.backend == "postgresql"
    assert settings.is_sqlite is False


def test_an_unsupported_backend_is_rejected_at_load_time() -> None:
    with pytest.raises(ValueError, match="sqlite or postgresql"):
        DbSettings(url="mysql://user@host/db")


def test_the_engine_answers(factory: sessionmaker[Session]) -> None:
    assert healthcheck(factory.kw["bind"]) is True


def test_sqlite_enforces_foreign_keys(session: Session) -> None:
    """Without the pragma, ON DELETE CASCADE is silently ignored on SQLite."""
    run = models.Run(customer_name="C", order_number="O", configuration_id="G")
    session.add(run)
    session.flush()
    session.add(
        models.Finding(
            run_id=run.id, finding_id="F-01", type="value_mismatch", severity="high", title="t"
        )
    )
    session.flush()

    session.delete(run)
    session.flush()
    assert session.execute(sa.select(sa.func.count()).select_from(models.Finding)).scalar_one() == 0


def test_timestamps_come_back_timezone_aware(session: Session) -> None:
    run = models.Run(customer_name="C", order_number="O", configuration_id="G")
    session.add(run)
    session.flush()
    session.expire(run)
    assert run.created_at.tzinfo is not None


def test_json_columns_round_trip(session: Session) -> None:
    session.add(models.Config(configuration_id="C-1", sha256="a", content={"a": [1, 2]}))
    session.flush()
    row = session.execute(sa.select(models.Config)).scalar_one()
    assert row.content == {"a": [1, 2]}


def test_every_design_doc_table_exists() -> None:
    expected = {
        "users",
        "runs",
        "run_files",
        "configs",
        "rules",
        "findings",
        "run_stages",
        "llm_calls",
        "attribute_aliases",
        "audit_log",
        "config_elements",
        "traces",
        "artifact_types",
        "run_scopes",
        "named_values",
        "check_definitions",
        "compliance_rules",
        "llm_cache",
        "final_reports",
    }
    assert expected <= set(models.Base.metadata.tables)


# --- fingerprint ---------------------------------------------------------------------


def test_the_same_files_give_the_same_fingerprint() -> None:
    assert repository.fingerprint(["a", "b"]) == repository.fingerprint(["a", "b"])


def test_upload_order_does_not_change_the_fingerprint() -> None:
    assert repository.fingerprint(["a", "b"]) == repository.fingerprint(["b", "a"])


def test_a_check_version_change_changes_the_fingerprint() -> None:
    """A check change must invalidate the duplicate shortcut."""
    assert repository.fingerprint(["a"], ["c:1"]) != repository.fingerprint(["a"], ["c:2"])


def test_file_hashing_matches_the_content(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "f.bin"
    path.write_bytes(b"hello")
    assert repository.file_sha256(path) == hashlib.sha256(b"hello").hexdigest()


# --- admin configuration ----------------------------------------------------------------


def test_an_empty_database_still_checks_the_default_categories(session: Session) -> None:
    """An empty table must not mean "check nothing"."""
    admin = repository.load_admin_config(session)
    assert len(admin.categories) == len(DEFAULT_CATEGORIES)
    assert admin.checks == ()


def test_configured_categories_replace_the_defaults(session: Session) -> None:
    session.add(models.ReversePassCategoryRow(name="Only filters", kinds=["filters"], checked=True))
    session.flush()
    admin = repository.load_admin_config(session)
    assert len(admin.categories) == 1
    assert admin.categories[0].kinds == ("filters",)


def test_only_active_checks_are_loaded(session: Session) -> None:
    session.add(models.CheckDefinitionRow(name="on", expression="1 == 1", is_active=True))
    session.add(models.CheckDefinitionRow(name="off", expression="1 == 2", is_active=False))
    session.flush()
    assert [c.name for c in repository.load_admin_config(session).checks] == ["on"]


def test_named_values_load_with_their_locator(session: Session) -> None:
    session.add(
        models.NamedValueRow(
            name="billing_count",
            report_type="billing",
            sheet="Summary",
            locator={"kind": "label", "label": "Billing count", "value_column": 1},
        )
    )
    session.flush()
    named = repository.load_admin_config(session).named_values
    assert len(named) == 1
    assert named[0].label == "Billing count"  # type: ignore[union-attr]


def test_an_empty_masked_column_table_falls_back_to_the_defaults(session: Session) -> None:
    """ADR-003: an empty table must never mean "mask nothing"."""
    assert repository.load_masked_columns(session) == DEFAULT_MASKED_COLUMNS


def test_configured_masked_columns_replace_the_defaults(session: Session) -> None:
    session.add(models.MaskedColumn(pattern="CUSTOM_ID"))
    session.flush()
    assert repository.load_masked_columns(session) == ("CUSTOM_ID",)


def test_aliases_are_scoped_to_the_customer(session: Session) -> None:
    session.add(models.AttributeAlias(canonical_name="score", alias="SCORE_V3"))
    session.add(models.AttributeAlias(canonical_name="income", alias="INC", customer_name="Acme"))
    session.flush()

    general = repository.load_aliases(session, "Other")
    assert general.resolve("SCORE_V3") == "score"
    assert general.knows("INC") is False
    assert repository.load_aliases(session, "Acme").knows("INC") is True


# --- config capture -----------------------------------------------------------------------


def test_a_new_config_is_version_one(session: Session) -> None:
    row = repository.capture_config(session, "CFG-1", "Acme", {"a": 1}, "sha-a")
    assert row.version == 1


def test_an_unchanged_config_is_not_versioned_again(session: Session) -> None:
    first = repository.capture_config(session, "CFG-1", "Acme", {"a": 1}, "sha-a")
    second = repository.capture_config(session, "CFG-1", "Acme", {"a": 1}, "sha-a")
    assert first.id == second.id


def test_a_changed_config_becomes_the_next_version(session: Session) -> None:
    repository.capture_config(session, "CFG-1", "Acme", {"a": 1}, "sha-a")
    second = repository.capture_config(session, "CFG-1", "Acme", {"a": 2}, "sha-b")
    assert second.version == 2


# --- retention ------------------------------------------------------------------------------


def test_expiry_defaults_to_the_retention_window() -> None:
    created = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert repository.expiry_from(created).date() == dt.date(2026, 4, 1)


def test_purging_deletes_expired_runs_and_their_files(session: Session, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "runs" / "1").mkdir(parents=True)
    stored = data_dir / "runs" / "1" / "osl.docx"
    stored.write_bytes(b"x")

    run = models.Run(
        customer_name="C",
        order_number="O",
        configuration_id="G",
        expires_at=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )
    session.add(run)
    session.flush()
    session.add(
        models.RunFile(
            run_id=run.id,
            kind="osl",
            filename="osl.docx",
            storage_key="runs/1/osl.docx",
            sha256="a",
            size_bytes=1,
        )
    )
    session.flush()

    assert repository.purge_expired(session, data_dir) == 1
    assert not stored.exists()


def test_purging_keeps_usage_statistics(session: Session, tmp_path: Path) -> None:
    """Aggregated usage survives the run it came from."""
    run = models.Run(
        customer_name="C",
        order_number="O",
        configuration_id="G",
        expires_at=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
    )
    session.add(run)
    session.flush()
    session.add(models.LlmCall(run_id=run.id, stage="s2_extract", provider="mock", model="m"))
    session.flush()

    repository.purge_expired(session, tmp_path)
    calls = list(session.execute(sa.select(models.LlmCall)).scalars())
    assert len(calls) == 1
    assert calls[0].run_id is None


def test_a_live_run_is_not_purged(session: Session, tmp_path: Path) -> None:
    run = models.Run(
        customer_name="C",
        order_number="O",
        configuration_id="G",
        expires_at=dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc),
    )
    session.add(run)
    session.flush()
    assert repository.purge_expired(session, tmp_path) == 0
