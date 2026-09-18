"""Shared dependencies: settings, sessions, and the single auth seam.

Every router depends on :func:`current_user`. It is a no-op in v1 because there is no
login, but having one place that every route already calls is what makes adding login
later a change to one function rather than to every endpoint (ADR-008).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Final, Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from vigilai.db.settings import DbSettings
from vigilai.llm.settings import LLMSettings

__all__ = [
    "CurrentUser",
    "current_user",
    "get_session",
    "get_db_settings",
    "get_llm_settings",
    "get_data_dir",
]

_LOG: Final = logging.getLogger(__name__)


class CurrentUser:
    """Who is making this request.

    v1 has no login, so every request is the same anonymous operator. The type exists so
    handlers can already write ``user.name`` into the audit log and keep doing so
    unchanged once login lands.

    Attributes:
        id: The user row id, ``None`` while the table is empty.
        name: A display name for the audit log.
        is_admin: Whether admin routes are permitted. True in v1; the admin-ui is
            protected by being on a separate URL, not by a role (ADR-008).
    """

    __slots__ = ("id", "name", "is_admin")

    def __init__(self, id: int | None = None, name: str = "anonymous", is_admin: bool = True):
        """Initialise the caller.

        Args:
            id: The user row id.
            name: A display name.
            is_admin: Whether admin routes are permitted.
        """
        self.id = id
        self.name = name
        self.is_admin = is_admin


def current_user() -> CurrentUser:
    """The single auth dependency (ADR-008).

    Returns:
        The anonymous operator. Replace the body to add login; no route changes.
    """
    return CurrentUser()


@lru_cache(maxsize=1)
def get_db_settings() -> DbSettings:
    """Read the database settings once per process.

    Returns:
        The settings.
    """
    return DbSettings.from_env()


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    """Read the adapter settings once per process.

    Returns:
        The settings.
    """
    return LLMSettings.from_env()


def get_data_dir(request: Request) -> Path:
    """Where uploads and generated files live.

    Read from application state rather than from the environment, so the directory a
    caller passed to :func:`~vigilai.api.app.create_app` is the one actually used. The
    environment-backed accessors are cached per process and would otherwise silently
    win over an injected setting.

    Args:
        request: The incoming request, which carries the app's configuration.

    Returns:
        The shared volume path.
    """
    data_dir: Path = request.app.state.data_dir
    return data_dir


def get_session(request: Request) -> Iterator[Session]:
    """Open a session for one request.

    Committed when the handler returns and rolled back on any exception, so a failed
    request never leaves a half-written run behind.

    Args:
        request: The incoming request, which carries the app's session factory.

    Yields:
        The session.
    """
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
