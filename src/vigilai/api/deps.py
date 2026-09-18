"""Shared dependencies: settings, sessions, and the single auth seam.

Every router depends on :func:`current_user`, which is why adding login was a change to
one function rather than to every endpoint (ADR-008). It resolves the caller and, when
the relevant switch is on, refuses an unauthenticated one.

**There is always a current user** (ADR-022). With login off it is the seeded
placeholder, so nothing downstream stores a nullable author or asks whether
authentication is enabled.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Final, Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from vigilai.auth.accounts import ensure_placeholder
from vigilai.auth.sessions import COOKIE_NAME, resolve_session
from vigilai.auth.settings import AuthSettings
from vigilai.db.settings import DbSettings
from vigilai.llm.settings import LLMSettings

__all__ = [
    "CurrentUser",
    "current_user",
    "require_admin",
    "get_session",
    "get_db_settings",
    "get_llm_settings",
    "get_auth_settings",
    "get_data_dir",
]

_LOG: Final = logging.getLogger(__name__)


class CurrentUser:
    """Who is making this request.

    There is always one. With the relevant switch off it is the placeholder account,
    which reads as "no login was enabled" rather than as a claim that a person acted.

    Attributes:
        id: The user row id. Always set, because the placeholder is a real row.
        name: A display name for the audit log and the screens that show who did what.
        email: The account's address.
        role: ``admin`` or ``user``.
        is_admin: Whether admin routes are permitted.
        is_placeholder: Whether this is the stand-in used while login is off.
        must_change_password: Whether every request but the password change should be
            refused until a new password is set.
    """

    __slots__ = (
        "id",
        "name",
        "email",
        "role",
        "is_admin",
        "is_placeholder",
        "must_change_password",
    )

    def __init__(
        self,
        id: int | None = None,
        name: str = "anonymous",
        email: str = "",
        role: str = "admin",
        is_admin: bool = True,
        is_placeholder: bool = False,
        must_change_password: bool = False,
    ):
        """Initialise the caller.

        Args:
            id: The user row id.
            name: A display name.
            email: The account's address.
            role: ``admin`` or ``user``.
            is_admin: Whether admin routes are permitted.
            is_placeholder: Whether this is the stand-in used while login is off.
            must_change_password: Whether a password change is outstanding.
        """
        self.id = id
        self.name = name
        self.email = email
        self.role = role
        self.is_admin = is_admin
        self.is_placeholder = is_placeholder
        self.must_change_password = must_change_password


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


def get_auth_settings(request: Request) -> AuthSettings:
    """The authentication switches for this app.

    Read from application state so a test can inject them, the same reason
    :func:`get_data_dir` does.

    Args:
        request: The incoming request.

    Returns:
        The settings.
    """
    settings: AuthSettings = request.app.state.auth_settings
    return settings


#: Paths that must work before a caller has done anything, including signing in and
#: clearing an outstanding password change.
_ALWAYS_OPEN: Final[tuple[str, ...]] = (
    "/auth/login",
    "/auth/logout",
    "/auth/config",
    "/auth/me",
    "/auth/change-password",
)


def current_user(
    request: Request,
    session: Session = Depends(get_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> CurrentUser:
    """The single auth dependency (ADR-008, ADR-022).

    Args:
        request: The incoming request, for its cookie and its path.
        session: The request's database session.
        settings: The authentication switches.

    Returns:
        The signed-in account, or the placeholder when the relevant switch is off.

    Raises:
        HTTPException: 401 when a switch that applies to this path is on and the
            request carries no valid session, or 403 when a password change is
            outstanding and the request is not the change itself.
    """
    path = request.url.path
    is_admin_path = "/admin/" in path or path.endswith("/admin")
    required = settings.admin_auth if is_admin_path else settings.user_auth

    user = resolve_session(session, settings, request.cookies.get(COOKIE_NAME, ""))
    if user is None:
        if required and not any(path.endswith(open_path) for open_path in _ALWAYS_OPEN):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in to continue")
        row = ensure_placeholder(session)
        return CurrentUser(
            id=row.id,
            name=row.name,
            email=row.email,
            role="user",
            # With the switch off nothing is gated by role, which is how the product
            # behaved before login existed.
            is_admin=not settings.admin_auth,
            is_placeholder=True,
        )

    if user.must_change_password and not path.endswith("/auth/change-password"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "set a new password before continuing")

    return CurrentUser(
        id=user.id,
        name=user.name or user.username,
        email=user.email,
        role=user.role,
        is_admin=user.role == "admin",
        must_change_password=user.must_change_password,
    )


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Guard admin routes.

    Args:
        user: The caller.

    Returns:
        The caller.

    Raises:
        HTTPException: 403 when the caller is signed in without the admin role, and
            401 when admin login is on and nobody is signed in.
    """
    if user.is_admin:
        return user
    if user.is_placeholder:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in to continue")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "this action needs an administrator")
