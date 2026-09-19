"""Tests for the worker loop."""

from __future__ import annotations

from pathlib import Path
import pytest
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.db.queue import JobQueue
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.llm.settings import LLMSettings
from greenlight_ai.worker.app import TASK_PURGE, TASK_RUN_PIPELINE, Worker


@pytest.fixture()
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'w.db'}"))
    create_all(engine)
    return session_factory(engine)


@pytest.fixture()
def worker(factory: sessionmaker[Session], tmp_path: Path) -> Worker:
    return Worker(factory, tmp_path / "data", is_sqlite=True, llm_settings=LLMSettings())


def _enqueue(factory: sessionmaker[Session], task: str, run_id: int | None = None) -> int:
    with factory() as session:
        job = JobQueue(session, is_sqlite=True).enqueue(task, run_id=run_id)
        session.commit()
        return job.id


def test_an_empty_queue_does_nothing(worker: Worker) -> None:
    assert worker.run_once() is False


def test_a_job_this_worker_cannot_handle_is_left_alone(
    worker: Worker, factory: sessionmaker[Session]
) -> None:
    """A task this build does not know may belong to a newer one, so it is not claimed."""
    job_id = _enqueue(factory, "nonsense")
    assert worker.run_once() is False
    with factory() as session:
        assert session.get(models.Job, job_id).status == "queued"


def test_the_purge_task_runs(worker: Worker, factory: sessionmaker[Session]) -> None:
    job_id = _enqueue(factory, TASK_PURGE)
    assert worker.run_once() is True
    with factory() as session:
        assert session.get(models.Job, job_id).status == "done"


def test_a_job_for_a_missing_run_fails_and_is_retried(
    worker: Worker, factory: sessionmaker[Session]
) -> None:
    job_id = _enqueue(factory, TASK_RUN_PIPELINE, run_id=4242)
    worker.run_once()
    with factory() as session:
        job = session.get(models.Job, job_id)
    assert job.status == "queued"
    assert "does not exist" in job.last_error


def test_a_run_awaiting_a_retry_stays_queued_not_failed(
    worker: Worker, factory: sessionmaker[Session]
) -> None:
    """The UI must not flash 'failed' for a run that is about to be retried."""
    with factory() as session:
        run = models.Run(customer_name="C", order_number="O", configuration_id="G")
        session.add(run)
        session.flush()
        JobQueue(session, is_sqlite=True).enqueue(TASK_RUN_PIPELINE, run_id=run.id)
        run_id = run.id
        session.commit()

    worker.run_once()  # fails: the run has no files
    with factory() as session:
        assert session.get(models.Run, run_id).status == "queued"


def test_a_run_is_marked_failed_once_the_retries_run_out(
    worker: Worker, factory: sessionmaker[Session]
) -> None:
    with factory() as session:
        run = models.Run(customer_name="C", order_number="O", configuration_id="G")
        session.add(run)
        session.flush()
        JobQueue(session, is_sqlite=True).enqueue(TASK_RUN_PIPELINE, run_id=run.id, max_attempts=1)
        run_id = run.id
        session.commit()

    worker.run_once()
    with factory() as session:
        stored = session.get(models.Run, run_id)
        assert stored.status == "failed"
        assert stored.error
        assert stored.finished_at is not None


def test_the_loop_stops_when_asked(worker: Worker, factory: sessionmaker[Session]) -> None:
    _enqueue(factory, TASK_PURGE)
    worker.stop()
    assert worker.run_forever() == 0


def test_the_loop_processes_what_it_finds(worker: Worker, factory: sessionmaker[Session]) -> None:
    _enqueue(factory, TASK_PURGE)
    _enqueue(factory, TASK_PURGE)
    assert worker.run_forever(max_iterations=3) == 2
