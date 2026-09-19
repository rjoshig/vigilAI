"""The data layer: models, sessions, the job queue, and the repository.

One relational database holds the data and the queue; `DATABASE_URL` selects SQLite or
Postgres and nothing else changes (ADR-017).
"""

from greenlight_ai.db.cache import DbCache, record_calls
from greenlight_ai.db.models import Base
from greenlight_ai.db.queue import ClaimedJob, JobQueue
from greenlight_ai.db.session import (
    create_all,
    create_engine,
    healthcheck,
    session_factory,
    session_scope,
)
from greenlight_ai.db.settings import DbSettings

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
