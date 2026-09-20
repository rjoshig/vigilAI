"""The worker: claim a job, run it, record the outcome, repeat.

A polling loop rather than ``LISTEN/NOTIFY``, because the queue has to work on SQLite
too (ADR-017). At this scale — a few runs a day, minutes each — a one-second poll is
indistinguishable from a push and it has no backend-specific machinery.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Callable, Final, Mapping, Sequence

from sqlalchemy.orm import Session, sessionmaker

from sqlalchemy.exc import SQLAlchemyError

from greenlight_ai.auth.sessions import purge_expired_sessions
from greenlight_ai.training.lifecycle import purge_deleted_rules
from greenlight_ai.db import models, repository
from greenlight_ai.db.queue import ClaimedJob, JobQueue
from greenlight_ai.db.session import create_all, create_engine, session_factory, session_scope
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.db.types import utcnow
from greenlight_ai.llm.settings import LLMSettings, resolved_llm_settings
from greenlight_ai.config.store import resolve
from greenlight_ai.worker.replay import replay_candidate
from greenlight_ai.worker.runner import execute_run, recheck_run

__all__ = ["Worker", "TASK_RUN_PIPELINE", "TASK_RECHECK", "TASK_PURGE", "TASK_REPLAY", "main"]

_LOG: Final = logging.getLogger("greenlight_ai.worker")

TASK_RUN_PIPELINE: Final[str] = "run_pipeline"
TASK_RECHECK: Final[str] = "recheck"
TASK_PURGE: Final[str] = "purge"
#: Evaluate a drafted rule against recent finalized runs (Phase 6.13e). It re-parses
#: stored files, so it belongs in the worker rather than in a request.
TASK_REPLAY: Final[str] = "replay"

#: How long to wait when there was nothing to do.
IDLE_SLEEP_SECONDS: Final[float] = 1.0

#: A claim older than this is treated as abandoned, so a killed worker's job is picked
#: up by another rather than sitting in ``running`` forever.
STALE_CLAIM_SECONDS: Final[int] = 900

#: How often to make sure a purge job is queued. The worker schedules its own retention
#: sweep so a deployment needs no cron entry; several workers racing to queue one is
#: harmless because the queue is idempotent about it.
PURGE_INTERVAL_SECONDS: Final[int] = 24 * 60 * 60


class Worker:
    """Claims and runs jobs until told to stop."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        data_dir: Path,
        is_sqlite: bool,
        llm_settings: LLMSettings | None = None,
    ) -> None:
        """Initialise the worker.

        Args:
            factory: The session factory.
            data_dir: The shared volume.
            is_sqlite: Which claiming strategy the queue should use.
            llm_settings: Adapter settings; read from the environment when omitted.
        """
        self._factory = factory
        self._data_dir = data_dir
        self._is_sqlite = is_sqlite
        self._llm_settings = llm_settings or LLMSettings.from_env()
        self._stopping = False
        self._last_purge_scheduled = 0.0
        self._handlers: Mapping[str, Callable[[ClaimedJob], None]] = {
            TASK_RUN_PIPELINE: self._run_pipeline,
            TASK_RECHECK: self._recheck,
            TASK_PURGE: self._purge,
            TASK_REPLAY: self._replay,
        }

    def stop(self) -> None:
        """Ask the loop to finish the current job and exit."""
        self._stopping = True

    def run_forever(self, max_iterations: int | None = None) -> int:
        """Poll for work until stopped.

        Args:
            max_iterations: Stop after this many polls. Used by tests; ``None`` runs
                until a signal arrives.

        Returns:
            How many jobs were processed.
        """
        processed = 0
        iterations = 0
        _LOG.info("worker started (data_dir=%s)", self._data_dir)

        while not self._stopping:
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1
            self.ensure_purge_scheduled()

            if self.run_once():
                processed += 1
            elif max_iterations is None:
                time.sleep(IDLE_SLEEP_SECONDS)

        _LOG.info("worker stopped after %d job(s)", processed)
        return processed

    def ensure_purge_scheduled(self) -> bool:
        """Queue the retention sweep if one is not already waiting.

        Args:
            None.

        Returns:
            ``True`` when a purge job was queued.
        """
        now = time.monotonic()
        if self._last_purge_scheduled and now - self._last_purge_scheduled < PURGE_INTERVAL_SECONDS:
            return False
        self._last_purge_scheduled = now

        with session_scope(self._factory) as session:
            queue = JobQueue(session, self._is_sqlite)
            if queue.queued_count(TASK_PURGE):
                return False
            queue.enqueue(TASK_PURGE)
        _LOG.info("scheduled the retention purge")
        return True

    def run_once(self) -> bool:
        """Claim and run at most one job.

        Returns:
            ``True`` when a job was processed.
        """
        with session_scope(self._factory) as session:
            queue = JobQueue(session, self._is_sqlite)
            queue.reclaim_stale(STALE_CLAIM_SECONDS)
            job = queue.claim(list(self._handlers))

        if job is None:
            return False

        handler = self._handlers.get(job.task)
        if handler is None:
            _LOG.error("job %d has unknown task %r", job.id, job.task)
            with session_scope(self._factory) as session:
                JobQueue(session, self._is_sqlite).fail(job.id, f"unknown task {job.task!r}")
            return True

        try:
            handler(job)
        except Exception as exc:  # noqa: BLE001 - the loop must survive any task failure
            self._handle_failure(job, exc)
            return True

        with session_scope(self._factory) as session:
            JobQueue(session, self._is_sqlite).finish(job.id)
        return True

    def _handle_failure(self, job: ClaimedJob, exc: Exception) -> None:
        """Record a task failure and decide about a retry.

        Args:
            job: The job that failed.
            exc: What went wrong. Only its type and message are stored, never file
                content (ADR-003).
        """
        # PipelineError already names its stage, so prefixing the class name again
        # produces "PipelineError: s1_parse: …" in the UI. Keep the message readable.
        from greenlight_ai.pipeline.run import PipelineError

        message = str(exc) if isinstance(exc, PipelineError) else f"{type(exc).__name__}: {exc}"
        _LOG.error("job %d (%s) raised %s", job.id, job.task, type(exc).__name__)

        with session_scope(self._factory) as session:
            queue = JobQueue(session, self._is_sqlite)
            will_retry = queue.fail(job.id, message)

            if job.run_id is not None:
                run = session.get(models.Run, job.run_id)
                if run is not None:
                    # A run awaiting a retry stays queued so the UI does not flash
                    # "failed" and then recover; only a dead job marks the run failed.
                    run.status = "queued" if will_retry else "failed"
                    run.error = message[:2000]
                    if not will_retry:
                        run.finished_at = utcnow()

    def _run_pipeline(self, job: ClaimedJob) -> None:
        """Execute a run.

        Args:
            job: The claimed job.

        Raises:
            ValueError: When the job carries no run id.
        """
        if job.run_id is None:
            raise ValueError(f"job {job.id} has no run_id")
        execute_run(self._factory, job.run_id, self._data_dir, self._settings_now())

    def _recheck(self, job: ClaimedJob) -> None:
        """Re-check a run after an edit.

        Args:
            job: The claimed job.

        Raises:
            ValueError: When the job carries no run id.
        """
        if job.run_id is None:
            raise ValueError(f"job {job.id} has no run_id")
        recheck_run(self._factory, job.run_id, self._data_dir, self._settings_now())

    def _replay(self, job: ClaimedJob) -> None:
        """Evaluate a candidate rule against recent finalized runs.

        Args:
            job: The claimed job, carrying the candidate id.

        Raises:
            ValueError: When the job names no candidate.
        """
        candidate_id = int(dict(job.payload or {}).get("candidate_id") or 0)
        if not candidate_id:
            raise ValueError(f"job {job.id} has no candidate_id")

        with session_scope(self._factory) as session:
            candidate = session.get(models.RuleCandidate, candidate_id)
            if candidate is None:
                _LOG.info("replay: candidate %s is gone", candidate_id)
                return
            limit = int(resolve(session, "training.replay_runs").value)
            candidate.replay = replay_candidate(session, candidate, self._data_dir, limit)
            _LOG.info(
                "replayed candidate %s over %s run(s)",
                candidate_id,
                candidate.replay.get("runs_examined", 0),
            )

    def _settings_now(self) -> LLMSettings:
        """Adapter settings as they resolve at this moment.

        Read per job rather than once at startup, so a provider or model an
        administrator changed in the console applies to the next run without
        restarting the worker (ADR-023). A database the worker cannot read falls back
        to what it started with, because a settings lookup must not be the thing that
        fails a run.

        Returns:
            The effective settings.
        """
        try:
            with session_scope(self._factory) as session:
                return resolved_llm_settings(session)
        except SQLAlchemyError:
            _LOG.warning("could not read settings; using the ones this worker started with")
            return self._llm_settings

    def _purge(self, _job: ClaimedJob) -> None:
        """Delete runs past their retention window.

        Args:
            _job: The claimed job; the purge takes no arguments.
        """
        with session_scope(self._factory) as session:
            repository.purge_expired(session, self._data_dir)
            # Housekeeping rather than a control: a session past its expiry already
            # fails to resolve, so this only keeps the table from growing forever.
            gone = purge_expired_sessions(session)
            if gone:
                _LOG.info("removed %d expired session(s)", gone)
            # A rule deleted more than six months ago becomes permanent here. The row
            # survives as a tombstone: findings on old runs cite a rule by reference,
            # and a reference to nothing explains nothing (ADR-021).
            tombstoned = purge_deleted_rules(session)
            if tombstoned:
                _LOG.info("%d deleted rule(s) are now permanent", tombstoned)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the worker container.

    Args:
        argv: Command-line arguments.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(prog="greenlight-ai-worker", description="Run queued jobs.")
    parser.add_argument("--once", action="store_true", help="Process one job and exit.")
    parser.add_argument(
        "--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    db_settings = DbSettings.from_env()
    engine = create_engine(db_settings)
    create_all(engine)
    factory = session_factory(engine)

    worker = Worker(factory, db_settings.data_dir, db_settings.is_sqlite)

    def _signal(_number: int, _frame: FrameType | None) -> None:
        """Finish the current job, then exit."""
        _LOG.info("shutdown requested; finishing the current job")
        worker.stop()

    signal.signal(signal.SIGTERM, _signal)
    signal.signal(signal.SIGINT, _signal)

    if args.once:
        worker.run_once()
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
