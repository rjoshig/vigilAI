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
from vigilai.auth.settings import AuthSettings, resolved_auth_settings
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
        username: What is typed at the sign-in prompt.
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
        "username",
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
        username: str = "",
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
            username: What is typed at the prompt.
            name: A display name.
            email: The account's address.
            role: ``admin`` or ``user``.
            is_admin: Whether admin routes are permitted.
            is_placeholder: Whether this is the stand-in used while login is off.
            must_change_password: Whether a password change is outstanding.
        """
        self.id = id
        self.username = username
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


def get_auth_settings(request: Request, session: Session = Depends(get_session)) -> AuthSettings:
    """The authentication switches for this request.

    Resolved per request rather than once at startup, so a change made in the admin
    console takes effect on the next request instead of the next deployment
    (ADR-023). The app's own settings are the environment layer beneath, which is
    also how a test injects them.

    Args:
        request: The incoming request.
        session: The request's database session.

    Returns:
        The effective settings.
    """
    base: AuthSettings = request.app.state.auth_settings
    if not request.app.state.runtime_settings:
        return base
    return resolved_auth_settings(session, _env_for(base), bind_host=base.bind_host)


def _env_for(base: AuthSettings) -> dict[str, str]:
    """The environment layer, expressed as the variables the registry reads.

    Taking it from the settings object rather than from ``os.environ`` is what lets a
    test inject an environment without touching the process's own.

    Args:
        base: The settings the app was built with.

    Returns:
        A mapping the settings registry can read.
    """
    return {
        "VIGILAI_ADMIN_AUTH": str(base.admin_auth).lower(),
        "VIGILAI_USER_AUTH": str(base.user_auth).lower(),
        "VIGILAI_SESSION_TTL_S": str(base.session_ttl_s),
        "VIGILAI_SESSION_IDLE_S": str(base.idle_ttl_s),
        "VIGILAI_MIN_PASSWORD_LENGTH": str(base.min_password_length),
        "VIGILAI_LOCKOUT_THRESHOLD": str(base.lockout_threshold),
        "VIGILAI_LOCKOUT_S": str(base.lockout_s),
        "VIGILAI_BIND_HOST": base.bind_host,
    }


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
            username=row.username,
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
        username=user.username,
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
