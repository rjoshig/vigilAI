"""The data layer: models, sessions, the job queue, and the repository.

One relational database holds the data and the queue; `DATABASE_URL` selects SQLite or
Postgres and nothing else changes (ADR-017).
"""

from vigilai.db.cache import DbCache, record_calls
from vigilai.db.models import Base
from vigilai.db.queue import ClaimedJob, JobQueue
from vigilai.db.session import (
    create_all,
    create_engine,
    healthcheck,
    session_factory,
    session_scope,
)
from vigilai.db.settings import DbSettings

__all__ = [
    "Base",
    "ClaimedJob",
    "DbCache",
    "DbSettings",
    "JobQueue",
    "create_all",
    "create_engine",
    "healthcheck",
    "record_calls",
    "session_factory",
    "session_scope",
]
