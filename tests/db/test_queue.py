"""Tests for the portable job queue (ADR-017)."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.db.queue import BACKOFF_SECONDS, JobQueue
from greenlight_ai.db.session import create_all, create_engine, session_factory
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.db.types import utcnow


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


def test_a_heartbeat_keeps_a_slow_job_from_looking_dead(queue: JobQueue, session: Session) -> None:
    """A slow job and a dead one looked identical, and one of them gets failed.

    `locked_at` was stamped once at claim time, so `reclaim_stale` was really asking
    "how long ago was this claimed", not "is anybody still working on it". A delivery
    with a long OSL against an endpoint answering near its timeout can hold a claim
    past the window legitimately. That was survivable while being reclaimed meant being
    run again; it stopped being survivable when reclaiming learned to give up on a job
    and fail its run.
    """
    run = models.Run(
        customer_name="Acme",
        order_number="ORD-SLOW",
        configuration_id="CFG-SLOW",
        status="running",
    )
    session.add(run)
    session.flush()
    job = queue.enqueue("run_pipeline", run_id=run.id, max_attempts=1)
    queue.claim()

    # Still working: the worker says so, and the claim stops looking abandoned.
    assert queue.touch(job.id) is True
    assert queue.reclaim_stale(older_than_seconds=3600) == 0

    session.refresh(run)
    assert run.status == "running", "a job being worked on must not have its run failed"
    session.refresh(job)
    assert job.status == "running"


def test_a_heartbeat_for_a_job_somebody_else_took_reports_it(
    queue: JobQueue, session: Session
) -> None:
    """Losing the claim is worth knowing about rather than writing over."""
    job = queue.enqueue("run_pipeline", run_id=1)
    queue.claim()
    queue.finish(job.id)

    assert queue.touch(job.id) is False


def test_a_job_that_outlives_its_workers_is_given_up_on(queue: JobQueue, session: Session) -> None:
    """A job that kills the worker holding it must stop being retried, like any other.

    `max_attempts` was consulted only in `fail`, which a worker that died never reached.
    So a payload that reliably takes the process down — an out-of-memory parse, a
    segfault in a native library, a container the scheduler keeps evicting — was
    reclaimed, re-claimed and killed the next worker too, for ever, with `attempts`
    climbing past its ceiling and nothing able to say the tool had stopped trying.
    """
    job = queue.enqueue("run_pipeline", run_id=1, max_attempts=2)

    for _ in range(2):
        assert queue.claim() is not None
        assert queue.reclaim_stale(older_than_seconds=0) in (0, 1)

    assert queue.claim() is None, "a job with no attempts left must not be handed out again"
    session.refresh(job)
    assert job.status == "failed"
    assert job.attempts <= job.max_attempts
    assert "no attempt remains" in job.last_error


def test_giving_up_on_a_job_also_fails_its_run(queue: JobQueue, session: Session) -> None:
    """A run left `running` with no job and nothing watching sits there for ever.

    `fail` leaves marking the run to the worker, which is where every other dead job is
    handled. The worker is exactly what is missing here, so the queue does it.
    """
    run = models.Run(
        customer_name="Acme",
        order_number="ORD-DEAD",
        configuration_id="CFG-DEAD",
        status="running",
    )
    session.add(run)
    session.flush()
    queue.enqueue("run_pipeline", run_id=run.id, max_attempts=1)

    queue.claim()
    queue.reclaim_stale(older_than_seconds=0)

    session.refresh(run)
    assert run.status == "failed"
    assert "no attempt remains" in run.error
    assert run.finished_at is not None


def test_a_finished_run_is_not_reopened_by_a_stale_job(queue: JobQueue, session: Session) -> None:
    """Only a run still queued or running is failed; a finalized one is left alone."""
    run = models.Run(
        customer_name="Acme",
        order_number="ORD-DONE",
        configuration_id="CFG-DONE",
        status="finalized",
    )
    session.add(run)
    session.flush()
    queue.enqueue("run_pipeline", run_id=run.id, max_attempts=1)

    queue.claim()
    queue.reclaim_stale(older_than_seconds=0)

    session.refresh(run)
    assert run.status == "finalized"


def test_giving_up_does_not_touch_a_job_with_attempts_left(
    queue: JobQueue, session: Session
) -> None:
    """The ordinary case is unchanged: a restart still resumes."""
    job = queue.enqueue("run_pipeline", run_id=1, max_attempts=3)
    queue.claim()
    assert queue.reclaim_stale(older_than_seconds=0) == 1
    session.refresh(job)
    assert job.status == "queued"
    assert job.last_error == ""


def test_the_locking_strategy_also_claims(factory: sessionmaker[Session]) -> None:
    """The Postgres path runs against SQLite too; only the SQL differs."""
    with factory() as session:
        JobQueue(session, is_sqlite=True).enqueue("run_pipeline", run_id=1)
        session.commit()
    with factory() as session:
        job = JobQueue(session, is_sqlite=False).claim()
        session.commit()
    assert job is not None
