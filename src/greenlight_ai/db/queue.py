"""The job queue: an ordinary table in whichever database is configured (ADR-017).

Procrastinate is Postgres-only, so the queue is ours. It needs to do three things and
does exactly those: survive a restart, let several workers claim different jobs without
stepping on each other, and back off between retries.

Claiming differs by backend and only by backend:

- **Postgres** uses ``SELECT … FOR UPDATE SKIP LOCKED``, so two workers never contend.
- **SQLite** uses a guarded single-statement ``UPDATE`` that names the row it expects to
  still be queued. SQLite serialises writers, so the guard is enough; the loser of a
  race updates zero rows and simply looks again.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.db.models import Job, Run
from greenlight_ai.db.types import utcnow

__all__ = ["JobQueue", "worker_name", "BACKOFF_SECONDS"]

_LOG: Final = logging.getLogger(__name__)

#: Delay before each retry, indexed by attempt number. A stage failure is usually a
#: model timeout or a restart, so the first retry is quick and the last gives a
#: recovering endpoint real time.
BACKOFF_SECONDS: Final[tuple[int, ...]] = (10, 60, 300)

#: What a job — and the run it belongs to — is told when no worker survives it. One
#: sentence in one place, because the row a person reads and the row the queue keeps
#: must not be able to say different things about the same event.
_ABANDONED: Final[str] = (
    "The worker holding this job stopped without reporting, and no attempt remains. "
    "A job that outlives its workers is not retried again."
)


def worker_name() -> str:
    """Identify this worker in ``jobs.locked_by``.

    Returns:
        Hostname and process id, which is enough to tell two containers apart when
        reading the table by hand.
    """
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """A job this worker owns until it finishes or crashes.

    Attributes:
        id: The job row id.
        task: Which task to run.
        run_id: The run this job belongs to, when it has one.
        payload: Task arguments.
        attempts: How many times this job has been tried, including now.
        max_attempts: After this many failures the job is dead.
    """

    id: int
    task: str
    run_id: int | None
    payload: Mapping[str, Any]
    attempts: int
    max_attempts: int

    @property
    def is_last_attempt(self) -> bool:
        """Whether a failure now means the job is dead.

        Returns:
            ``True`` when no retry remains, so the caller can mark the run failed with
            the error visible in the UI rather than leaving it queued forever.
        """
        return self.attempts >= self.max_attempts


class JobQueue:
    """Enqueue, claim, and finish jobs."""

    def __init__(self, session: Session, is_sqlite: bool) -> None:
        """Initialise the queue.

        Args:
            session: An open session.
            is_sqlite: Which claiming strategy to use. Taken as a flag rather than
                sniffed from the connection so a test can exercise either path.
        """
        self._session = session
        self._is_sqlite = is_sqlite

    def enqueue(
        self,
        task: str,
        run_id: int | None = None,
        payload: Mapping[str, Any] | None = None,
        max_attempts: int = 3,
        run_after: dt.datetime | None = None,
    ) -> Job:
        """Add a job.

        Args:
            task: The task name.
            run_id: The run this job belongs to.
            payload: Task arguments.
            max_attempts: How many times to try before giving up.
            run_after: Earliest time the job may be claimed.

        Returns:
            The queued job row.
        """
        job = Job(
            task=task,
            run_id=run_id,
            payload=dict(payload or {}),
            max_attempts=max_attempts,
            run_after=run_after or utcnow(),
        )
        self._session.add(job)
        self._session.flush()
        _LOG.info("queued job %d (%s) for run %s", job.id, task, run_id)
        return job

    def claim(self, tasks: Sequence[str] | None = None) -> ClaimedJob | None:
        """Take the next due job, if there is one.

        Args:
            tasks: Only claim these task names. All tasks when omitted.

        Returns:
            The claimed job, or ``None`` when nothing is due.
        """
        now = utcnow()
        conditions = [Job.status == "queued", Job.run_after <= now]
        if tasks:
            conditions.append(Job.task.in_(list(tasks)))

        if self._is_sqlite:
            return self._claim_sqlite(conditions, now)
        return self._claim_locking(conditions, now)

    def _claim_locking(self, conditions: list[Any], now: dt.datetime) -> ClaimedJob | None:
        """Claim using row locks (Postgres).

        Args:
            conditions: The due-job filter.
            now: The claim time.

        Returns:
            The claimed job, or ``None``.
        """
        job = self._session.execute(
            sa.select(Job)
            .where(*conditions)
            .order_by(Job.run_after, Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if job is None:
            return None
        return self._mark_running(job, now)

    def _claim_sqlite(self, conditions: list[Any], now: dt.datetime) -> ClaimedJob | None:
        """Claim using a guarded update (SQLite).

        Args:
            conditions: The due-job filter.
            now: The claim time.

        Returns:
            The claimed job, or ``None`` when nothing is due or another worker won.
        """
        candidate = self._session.execute(
            sa.select(Job.id).where(*conditions).order_by(Job.run_after, Job.id).limit(1)
        ).scalar_one_or_none()
        if candidate is None:
            return None

        # The status guard is what makes this safe: if another worker claimed the row
        # between the select and here, this updates nothing and we report no work.
        updated = self._session.execute(
            sa.update(Job)
            .where(Job.id == candidate, Job.status == "queued")
            .values(status="running", locked_by=worker_name(), locked_at=now)
        )
        if updated.rowcount != 1:  # type: ignore[attr-defined]
            return None
        self._session.flush()
        job = self._session.get(Job, candidate)
        assert job is not None  # noqa: S101 - just updated it inside this transaction
        job.attempts += 1
        self._session.flush()
        return self._as_claimed(job)

    def _mark_running(self, job: Job, now: dt.datetime) -> ClaimedJob:
        """Record that this worker owns a job.

        Args:
            job: The job row.
            now: The claim time.

        Returns:
            The claimed job.
        """
        job.status = "running"
        job.locked_by = worker_name()
        job.locked_at = now
        job.attempts += 1
        self._session.flush()
        return self._as_claimed(job)

    @staticmethod
    def _as_claimed(job: Job) -> ClaimedJob:
        """Convert a row into the immutable view a worker sees.

        Args:
            job: The job row.

        Returns:
            The claimed job.
        """
        return ClaimedJob(
            id=job.id,
            task=job.task,
            run_id=job.run_id,
            payload=dict(job.payload or {}),
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )

    def finish(self, job_id: int) -> None:
        """Mark a job done.

        Args:
            job_id: The job row id.
        """
        self._session.execute(
            sa.update(Job)
            .where(Job.id == job_id)
            .values(status="done", finished_at=utcnow(), last_error="")
        )

    def fail(self, job_id: int, error: str) -> bool:
        """Record a failure and schedule a retry if one remains.

        Args:
            job_id: The job row id.
            error: The failure, with no file content in it (ADR-003).

        Returns:
            ``True`` when the job will be retried, ``False`` when it is dead.
        """
        job = self._session.get(Job, job_id)
        if job is None:
            return False

        job.last_error = error[:2000]
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.finished_at = utcnow()
            _LOG.error(
                "job %d (%s) failed permanently after %d attempts", job.id, job.task, job.attempts
            )
            self._session.flush()
            return False

        delay = BACKOFF_SECONDS[min(job.attempts - 1, len(BACKOFF_SECONDS) - 1)]
        job.status = "queued"
        job.locked_by = ""
        job.locked_at = None
        job.run_after = utcnow() + dt.timedelta(seconds=delay)
        _LOG.warning("job %d (%s) failed; retrying in %ds", job.id, job.task, delay)
        self._session.flush()
        return True

    def cancel_jobs(self, run_id: int) -> bool | None:
        """Drop a run's pending jobs, unless one has already been taken.

        Args:
            run_id: The run whose work should not happen.

        Returns:
            ``None`` when the pending jobs were dropped, and ``False`` when a job for
            this run is already running — the caller then has a race to report rather
            than a cancellation to make. Reported rather than forced, because a job
            that has started has a worker holding it and killing that from here would
            leave the run half done with nothing watching.
        """
        running = self._session.execute(
            sa.select(sa.func.count())
            .select_from(Job)
            .where(Job.run_id == run_id, Job.status == "running")
        ).scalar_one()
        if int(running) > 0:
            return False

        pending = list(
            self._session.execute(
                sa.select(Job).where(Job.run_id == run_id, Job.status == "queued")
            ).scalars()
        )
        for job in pending:
            self._session.delete(job)
        _LOG.info("dropped %d pending job(s) for run %d", len(pending), run_id)
        return None

    def queue_position(self, run_id: int) -> int | None:
        """Report how many jobs are ahead of a run's job.

        Args:
            run_id: The run.

        Returns:
            The one-based position, or ``None`` when the run has no queued job, which is
            what the Runs screen shows while a run is already executing.
        """
        job = self._session.execute(
            sa.select(Job).where(Job.run_id == run_id, Job.status == "queued").limit(1)
        ).scalar_one_or_none()
        if job is None:
            return None
        ahead = self._session.execute(
            sa.select(sa.func.count())
            .select_from(Job)
            .where(
                Job.status == "queued",
                sa.or_(
                    Job.run_after < job.run_after,
                    sa.and_(Job.run_after == job.run_after, Job.id < job.id),
                ),
            )
        ).scalar_one()
        return int(ahead) + 1

    def pending_for(self, run_id: int, task: str) -> bool:
        """Whether a job of one kind is waiting or already running for a run.

        A re-check changes no status — it rebuilds findings and leaves the run in
        ``needs_review`` — so the only honest way for a screen to say *this is
        happening now* is to ask the queue. Adding a ninth run status would have said
        the same thing in a vocabulary every filter, label and tone map would then have
        to learn, for a job that takes seconds (Phase 6.23b).

        Args:
            run_id: The run.
            task: The task name, e.g. :data:`~greenlight_ai.worker.app.TASK_RECHECK`.

        Returns:
            ``True`` while such a job is queued or claimed.
        """
        return (
            self._session.execute(
                sa.select(sa.func.count())
                .select_from(Job)
                .where(
                    Job.run_id == run_id,
                    Job.task == task,
                    Job.status.in_(("queued", "running")),
                )
            ).scalar_one()
            > 0
        )

    def queued_count(self, task: str | None = None) -> int:
        """Count jobs waiting to run.

        Args:
            task: Restrict to one task name.

        Returns:
            The count, used for the per-order-number cap.
        """
        statement = sa.select(sa.func.count()).select_from(Job).where(Job.status == "queued")
        if task:
            statement = statement.where(Job.task == task)
        return int(self._session.execute(statement).scalar_one())

    def reclaim_stale(self, older_than_seconds: int = 900) -> int:
        """Return jobs whose worker died back to the queue, while attempts remain.

        A worker killed mid-run leaves a row marked ``running`` that nothing will ever
        finish. Reclaiming is what makes "kill a worker and restart" resume rather than
        hang (phase-3 acceptance criterion 4).

        **A job that keeps killing its worker is given up on, like any other failure.**
        ``max_attempts`` was only ever consulted in :meth:`fail`, which a worker that
        died never reached — so a job whose payload reliably takes the process down
        (an out-of-memory parse, a segfault in a native library, a container the
        scheduler keeps evicting) was reclaimed, re-claimed, and killed the next worker
        too, for ever, with ``attempts`` climbing past its ceiling and nothing in the
        product able to say it had stopped trying. It is marked failed here on the same
        terms `fail` would, so the run reports it and a person sees it.

        Args:
            older_than_seconds: How long a claim may be held before it is considered
                abandoned.

        Returns:
            How many jobs were returned to the queue. Jobs given up on are not counted:
            nothing was reclaimed for them.
        """
        cutoff = utcnow() - dt.timedelta(seconds=older_than_seconds)
        stale = (Job.status == "running", Job.locked_at < cutoff)

        # Read before the update, because a run whose job is given up on has to be told.
        # `fail` leaves that to the worker, which is where every other dead job is
        # handled — but the worker is precisely what is missing here, so a run left
        # `running` with no job and nothing watching would sit on the screen for ever.
        doomed = [
            row
            for row in self._session.execute(
                sa.select(Job.id, Job.run_id).where(*stale, Job.attempts >= Job.max_attempts)
            ).all()
        ]
        if doomed:
            self._session.execute(
                sa.update(Job)
                .where(Job.id.in_([job_id for job_id, _ in doomed]))
                .values(
                    status="failed",
                    finished_at=utcnow(),
                    locked_by="",
                    locked_at=None,
                    last_error=_ABANDONED,
                )
            )
            run_ids = [run_id for _, run_id in doomed if run_id is not None]
            if run_ids:
                self._session.execute(
                    sa.update(Run)
                    .where(Run.id.in_(run_ids), Run.status.in_(("queued", "running")))
                    .values(status="failed", error=_ABANDONED, finished_at=utcnow())
                )
            _LOG.error("gave up on %d stale job(s) with no attempts left", len(doomed))

        result = self._session.execute(
            sa.update(Job)
            .where(*stale, Job.attempts < Job.max_attempts)
            .values(status="queued", locked_by="", locked_at=None)
        )
        reclaimed = int(result.rowcount)  # type: ignore[attr-defined]
        if reclaimed:
            _LOG.warning("reclaimed %d stale job(s)", reclaimed)
        return reclaimed
