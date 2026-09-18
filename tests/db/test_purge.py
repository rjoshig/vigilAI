"""Tests for the retention purge (Phase 6)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import purge  # noqa: E402

from vigilai.db import models  # noqa: E402
from vigilai.db.session import create_all, create_engine, session_factory  # noqa: E402
from vigilai.db.settings import DbSettings  # noqa: E402


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'p.db'}"))
    create_all(engine)
    return session_factory(engine)


def _run(session: Session, data_dir: Path, *, expired: bool) -> models.Run:
    run = models.Run(
        customer_name="Acme",
        order_number="O-1",
        configuration_id="C-1",
        expires_at=dt.datetime(2020 if expired else 2099, 1, 1, tzinfo=dt.timezone.utc),
    )
    session.add(run)
    session.flush()
    stored = data_dir / "runs" / str(run.id) / "osl.docx"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(b"x" * 100)
    session.add(
        models.RunFile(
            run_id=run.id,
            kind="osl",
            filename="osl.docx",
            storage_key=f"runs/{run.id}/osl.docx",
            sha256="a",
            size_bytes=100,
        )
    )
    session.flush()
    return run


def test_nothing_expired_reports_so(factory: sessionmaker[Session], tmp_path: Path) -> None:
    with factory() as session:
        assert purge.describe(
            purge.expired_runs(session, dt.datetime.now(dt.timezone.utc)), tmp_path
        ) == ("Nothing has expired.")


def test_an_expired_run_is_listed_with_its_files(
    factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with factory() as session:
        _run(session, tmp_path, expired=True)
        session.commit()
        report = purge.describe(
            purge.expired_runs(session, dt.datetime.now(dt.timezone.utc)), tmp_path
        )
    assert "1 run(s) would be purged" in report
    assert "1 file(s)" in report
    assert "Aggregated usage statistics are kept" in report


def test_a_live_run_is_not_listed(factory: sessionmaker[Session], tmp_path: Path) -> None:
    with factory() as session:
        _run(session, tmp_path, expired=False)
        session.commit()
        assert purge.expired_runs(session, dt.datetime.now(dt.timezone.utc)) == []


def test_a_dry_run_changes_nothing(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Deleting a frozen report is not recoverable, so this is the default advice."""
    with factory() as session:
        run = _run(session, tmp_path, expired=True)
        run_id = run.id
        session.commit()

    monkeypatch.setenv("DATABASE_URL", str(factory.kw["bind"].url))
    monkeypatch.setenv("VIGILAI_DATA_DIR", str(tmp_path))
    assert purge.main(["--dry-run", "--log-level", "ERROR"]) == 0
    assert "nothing was deleted" in capsys.readouterr().out

    with factory() as session:
        assert session.get(models.Run, run_id) is not None
    assert (tmp_path / "runs" / str(run_id) / "osl.docx").exists()


def test_a_real_purge_deletes_the_run_and_its_files(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with factory() as session:
        run = _run(session, tmp_path, expired=True)
        run_id = run.id
        session.commit()

    monkeypatch.setenv("DATABASE_URL", str(factory.kw["bind"].url))
    monkeypatch.setenv("VIGILAI_DATA_DIR", str(tmp_path))
    assert purge.main(["--log-level", "ERROR"]) == 0

    with factory() as session:
        assert session.get(models.Run, run_id) is None
    assert not (tmp_path / "runs" / str(run_id) / "osl.docx").exists()


def test_usage_statistics_survive_the_purge(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard keeps its history after the runs behind it are gone."""
    with factory() as session:
        run = _run(session, tmp_path, expired=True)
        session.add(
            models.LlmCall(
                run_id=run.id, stage="s2_extract", provider="mock", model="m", prompt_tokens=100
            )
        )
        session.commit()

    monkeypatch.setenv("DATABASE_URL", str(factory.kw["bind"].url))
    monkeypatch.setenv("VIGILAI_DATA_DIR", str(tmp_path))
    purge.main(["--log-level", "ERROR"])

    with factory() as session:
        calls = list(session.execute(sa.select(models.LlmCall)).scalars())
    assert len(calls) == 1
    assert calls[0].run_id is None
    assert calls[0].prompt_tokens == 100


def test_an_override_window_can_expire_older_runs(
    factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    with factory() as session:
        run = _run(session, tmp_path, expired=False)
        run.created_at = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
        session.commit()

    monkeypatch.setenv("DATABASE_URL", str(factory.kw["bind"].url))
    monkeypatch.setenv("VIGILAI_DATA_DIR", str(tmp_path))
    purge.main(["--older-than-days", "30", "--dry-run", "--log-level", "ERROR"])
    assert "1 run(s) would be purged" in capsys.readouterr().out
