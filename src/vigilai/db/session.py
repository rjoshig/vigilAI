"""Engine and session helpers, portable across SQLite and Postgres (ADR-017)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Iterator

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from vigilai.db.models import Base
from vigilai.db.settings import DbSettings

__all__ = ["create_engine", "session_factory", "session_scope", "create_all", "healthcheck"]

_LOG: Final = logging.getLogger(__name__)


def create_engine(settings: DbSettings) -> Engine:
    """Build the engine for the configured backend.

    Args:
        settings: The database settings.

    Returns:
        A configured engine. SQLite gets foreign keys switched on and WAL journaling,
        neither of which is the default: without the first, ``ON DELETE CASCADE`` is
        silently ignored, and without the second a reader blocks a writer, which a
        polling worker does constantly.
    """
    options: dict[str, Any] = {"echo": settings.echo, "future": True}

    if settings.is_sqlite:
        path = _sqlite_path(settings.url)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the API serves requests on a thread pool and each one
        # takes its own session, so the connection is never shared between threads.
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        options["pool_size"] = settings.pool_size
        options["pool_pre_ping"] = True

    engine = sa.create_engine(settings.url, **options)

    if settings.is_sqlite:

        @sa.event.listens_for(engine, "connect")
        def _sqlite_pragmas(connection: Any, _record: Any) -> None:
            """Apply the pragmas SQLite needs to behave like the other backend."""
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    _LOG.info("database engine ready (%s)", settings.backend)
    return engine


def _sqlite_path(url: str) -> Path | None:
    """Extract the file path from a SQLite URL.

    Args:
        url: The SQLAlchemy URL.

    Returns:
        The path, or ``None`` for an in-memory database.
    """
    _, _, tail = url.partition(":///")
    if not tail or tail == ":memory:":
        return None
    return Path(tail)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory.

    Args:
        engine: The engine.

    Returns:
        A factory that produces sessions which do not expire objects on commit, so a
        request handler can still read an object it just wrote.
    """
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Run a unit of work in a transaction.

    Args:
        factory: The session factory.

    Yields:
        A session. Committed on success and rolled back on any exception, so a failed
        request cannot leave a half-written run behind.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine) -> None:
    """Create every table that does not yet exist.

    Alembic owns schema changes; this exists for tests and for a first run against an
    empty SQLite file, where a migration round-trip adds nothing.

    Args:
        engine: The engine.
    """
    Base.metadata.create_all(engine)
    _LOG.info("schema ensured (%d tables)", len(Base.metadata.tables))


def healthcheck(engine: Engine) -> bool:
    """Check that the database answers.

    Args:
        engine: The engine.

    Returns:
        ``True`` when a trivial query succeeds.
    """
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
        return True
    except sa.exc.SQLAlchemyError as exc:
        _LOG.error("database healthcheck failed: %s", type(exc).__name__)
        return False
