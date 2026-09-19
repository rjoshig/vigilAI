"""Tests for the portable job queue (ADR-017)."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from vigilai.db import models
from vigilai.db.queue import BACKOFF_SECONDS, JobQueue
from vigilai.db.session import create_all, create_engine, session_factory
from vigilai.db.settings import DbSettings
from vigilai.db.types import utcnow


@pytest.fixture()
def factory(tmp_path) -> sessionmaker[Session]:
    engine = create_engine(DbSettings(url=f"sqlite+pysqlite:///{tmp_path / 'q.db'}"))
    create_all(engine)
    return session_factory(engine)


@pytest.fixture()
def session(factory: sessionmaker[Session]):
    with factory() as s:
        yield s


@pytest.fixture()
def queue(session: Session) -> JobQueue:
    return JobQueue(session, is_sqlite=True)


def test_an_empty_queue_yields_nothing(queue: JobQueue) -> None:
    assert queue.claim() is None


def test_a_queued_job_can_be_claimed(queue: JobQueue, session: Session) -> None:
    queue.enqueue("run_pipeline", run_id=7, payload={"a": 1})
    job = queue.claim()
    assert job is not None
    assert job.task == "run_pipeline"
    assert job.run_id == 7
    assert job.payload == {"a": 1}
    assert job.attempts == 1


def test_a_claimed_job_is_not_claimed_twice(queue: JobQueue) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    assert queue.claim() is not None
    assert queue.claim() is None


def test_jobs_are_claimed_oldest_first(queue: JobQueue) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    queue.enqueue("run_pipeline", run_id=2)
    assert queue.claim().run_id == 1  # type: ignore[union-attr]
    assert queue.claim().run_id == 2  # type: ignore[union-attr]


def test_only_requested_tasks_are_claimed(queue: JobQueue) -> None:
    queue.enqueue("purge")
    assert queue.claim(["run_pipeline"]) is None
    assert queue.claim(["purge"]) is not None


def test_a_job_scheduled_for_later_is_not_due_yet(queue: JobQueue) -> None:
    queue.enqueue("run_pipeline", run_after=utcnow() + dt.timedelta(minutes=5))
    assert queue.claim() is None


def test_finishing_a_job_marks_it_done(queue: JobQueue, session: Session) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    job = queue.claim()
    assert job is not None
    queue.finish(job.id)
    assert session.get(models.Job, job.id).status == "done"


def test_a_failure_schedules_a_retry_with_backoff(queue: JobQueue, session: Session) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    job = queue.claim()
    assert job is not None

    assert queue.fail(job.id, "the model timed out") is True
    row = session.get(models.Job, job.id)
    assert row.status == "queued"
    assert row.last_error == "the model timed out"
    assert row.run_after > utcnow() + dt.timedelta(seconds=BACKOFF_SECONDS[0] - 2)


def test_a_job_dies_after_its_last_attempt(queue: JobQueue, session: Session) -> None:
    queue.enqueue("run_pipeline", run_id=1, max_attempts=2)
    for _ in range(2):
        job = queue.claim()
        assert job is not None
        retried = queue.fail(job.id, "still broken")
        session.execute(
            sa.update(models.Job).where(models.Job.id == job.id).values(run_after=utcnow())
        )
    assert retried is False
    assert session.get(models.Job, job.id).status == "failed"


def test_failing_an_unknown_job_reports_no_retry(queue: JobQueue) -> None:
    assert queue.fail(9999, "gone") is False


def test_queue_position_counts_jobs_ahead(queue: JobQueue) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    queue.enqueue("run_pipeline", run_id=2)
    queue.enqueue("run_pipeline", run_id=3)
    assert queue.queue_position(1) == 1
    assert queue.queue_position(3) == 3


def test_a_running_job_has_no_queue_position(queue: JobQueue) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    queue.claim()
    assert queue.queue_position(1) is None


def test_queued_count_can_be_filtered_by_task(queue: JobQueue) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    queue.enqueue("purge")
    assert queue.queued_count() == 2
    assert queue.queued_count("purge") == 1


def test_a_stale_claim_is_returned_to_the_queue(queue: JobQueue) -> None:
    """A worker killed mid-run must not leave its job stuck forever."""
    queue.enqueue("run_pipeline", run_id=1)
    queue.claim()
    assert queue.claim() is None
    assert queue.reclaim_stale(older_than_seconds=0) == 1
    assert queue.claim() is not None


def test_a_fresh_claim_is_not_reclaimed(queue: JobQueue) -> None:
    queue.enqueue("run_pipeline", run_id=1)
    queue.claim()
    assert queue.reclaim_stale(older_than_seconds=3600) == 0


def test_the_locking_strategy_also_claims(factory: sessionmaker[Session]) -> None:
    """The Postgres path runs against SQLite too; only the SQL differs."""
    with factory() as session:
        JobQueue(session, is_sqlite=True).enqueue("run_pipeline", run_id=1)
        session.commit()
    with factory() as session:
        job = JobQueue(session, is_sqlite=False).claim()
        session.commit()
    assert job is not None
