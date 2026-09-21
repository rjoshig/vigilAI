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
from typing import Callable, Final, Iterator, Sequence

from fastapi import Depends, HTTPException, Request, status, Query
from sqlalchemy.orm import Session

from greenlight_ai.auth.accounts import ensure_placeholder
from greenlight_ai.auth.roles import Capability, Role, capabilities_of, holds, normalize_roles
from greenlight_ai.auth.sessions import COOKIE_NAME, resolve_session
from greenlight_ai.auth.settings import AuthSettings, resolved_auth_settings
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.llm.settings import LLMSettings

__all__ = [
    "CurrentUser",
    "current_user",
    "require_admin",
    "require_capability",
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
        role: The strongest role held, kept for callers not yet moved to ``roles``.
        roles: Every role held, weakest first (ADR-049). Capabilities are the union.
        capabilities: What this caller may actually do. Resolved from ``roles``, and
            **empty when the deployment is not enforcing** — see :func:`current_user`.
            This is what every guard reads; no router asks about a role.
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
        "roles",
        "capabilities",
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
        roles: Sequence[str] | None = None,
        capabilities: frozenset[Capability] | None = None,
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
            role: The strongest role held.
            roles: Every role held; defaults to the one in ``role``.
            capabilities: What the caller may do; defaults to what ``roles`` grant.
            is_admin: Whether admin routes are permitted.
            is_placeholder: Whether this is the stand-in used while login is off.
            must_change_password: Whether a password change is outstanding.
        """
        self.id = id
        self.username = username
        self.name = name
        self.email = email
        self.role = role
        self.roles = normalize_roles(roles if roles is not None else [role])
        self.capabilities = (
            capabilities_of(self.roles) if capabilities is None else frozenset(capabilities)
        )
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
    caller passed to :func:`~greenlight_ai.api.app.create_app` is the one actually used. The
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
        "GREENLIGHT_AI_ADMIN_AUTH": str(base.admin_auth).lower(),
        "GREENLIGHT_AI_USER_AUTH": str(base.user_auth).lower(),
        "GREENLIGHT_AI_SESSION_TTL_S": str(base.session_ttl_s),
        "GREENLIGHT_AI_SESSION_IDLE_S": str(base.idle_ttl_s),
        "GREENLIGHT_AI_MIN_PASSWORD_LENGTH": str(base.min_password_length),
        "GREENLIGHT_AI_LOCKOUT_THRESHOLD": str(base.lockout_threshold),
        "GREENLIGHT_AI_LOCKOUT_S": str(base.lockout_s),
        "GREENLIGHT_AI_BIND_HOST": base.bind_host,
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
        # With the switch off nothing is gated, which is how the product behaved before
        # login existed (ADR-022): the placeholder holds `user` and `admin`, so what it
        # may do is everything. With the switch on, an unauthenticated caller has
        # reached a path that does not require a session — it may not use the console
        # on the strength of the placeholder's roles, so it is granted nothing.
        enforcing = settings.admin_auth
        return CurrentUser(
            id=row.id,
            username=row.username,
            name=row.name,
            email=row.email,
            role=row.role,
            roles=list(row.roles or []),
            capabilities=frozenset() if enforcing else capabilities_of(row.roles),
            # The roles above say what this account holds; this says what the
            # deployment is enforcing, which is nothing.
            is_admin=not enforcing,
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
        roles=list(user.roles or []),
        capabilities=capabilities_of(user.roles),
        # Read from the role list rather than from the legacy column, so an account
        # that holds `admin` is an administrator even if the two ever disagree.
        is_admin=holds(user.roles, Role.ADMIN),
        must_change_password=user.must_change_password,
    )


DELETE_WORD: Final[str] = "delete"


def require_delete_word(confirm: str = Query(default="")) -> None:
    """Refuse a delete unless the caller typed the word (ADR-032).

    Every admin delete asks the person to type ``delete``; the API enforces the same
    word so a script cannot skip the pause the screen imposes.

    Args:
        confirm: The ``?confirm=`` query value.

    Raises:
        HTTPException: 400 when the word was not typed.
    """
    if confirm.strip().lower() != DELETE_WORD:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"type {DELETE_WORD!r} to confirm; a delete cannot be undone",
        )


def require_capability(capability: Capability) -> Callable[..., CurrentUser]:
    """Build a guard that refuses a caller who may not do one particular thing.

    This is the only way a route asks about permission (ADR-049). Routes name the act
    — approve training, manage settings — rather than the role, so the matrix in
    :mod:`greenlight_ai.auth.roles` stays the only place that says who may do what.

    Args:
        capability: What the route needs.

    Returns:
        A FastAPI dependency yielding the caller, for use both as a router-level
        ``dependencies=[...]`` entry and as an endpoint parameter that wants the user.

    The refusal is **403, not 404**. The screen exists and is not theirs; pretending it
    does not exist makes a support conversation impossible, and there is nothing secret
    in the name of an endpoint the console links to.
    """

    def guard(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        """Refuse the caller unless they hold the capability.

        Args:
            user: The caller.

        Returns:
            The caller.

        Raises:
            HTTPException: 401 when nobody is signed in and the deployment wants them
                to be, 403 when somebody is signed in without this capability.
        """
        if capability in user.capabilities:
            return user
        if user.is_placeholder:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in to continue")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"this action needs the {_CAPABILITY_NEEDS[capability]}",
        )

    guard.__name__ = f"require_{capability.value}"
    return guard


#: How a refusal names what was missing. In the words of the job rather than the
#: constant, because the message reaches a person on a screen.
_CAPABILITY_NEEDS: Final[dict[Capability, str]] = {
    Capability.VIEW_ADMIN: "admin console",
    Capability.APPROVE_TRAINING: "ability to approve training",
    Capability.MANAGE_RULES: "ability to manage rules",
    Capability.TEACH_MODEL: "ability to teach the tool",
    Capability.MANAGE_REFERENCE: "ability to manage reference data",
    Capability.MANAGE_PRIVACY: "ability to manage masked columns",
    Capability.MANAGE_ARTIFACTS: "ability to manage artifact types",
    Capability.MANAGE_PROGRAMMES: "ability to manage delivery programmes",
    Capability.MANAGE_MEANING: "ability to manage meaning",
    Capability.MANAGE_USERS: "ability to manage accounts",
    Capability.MANAGE_SETTINGS: "ability to change settings",
}

#: The floor for the admin console: opening it at all, and reading what changes
#: nothing. Every other capability is asked for by the route that needs it.
require_admin: Final = require_capability(Capability.VIEW_ADMIN)
