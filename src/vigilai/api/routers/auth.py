"""Signing in, signing out, and changing a password (ADR-022).

These routes are open by design: a caller cannot be asked to authenticate before the
endpoint that authenticates them. Everything else in the API goes through
:func:`~vigilai.api.deps.current_user`.
"""

from __future__ import annotations

import logging
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from vigilai.api.deps import CurrentUser, current_user, get_auth_settings, get_session
from vigilai.api.schemas_auth import (
    AuthConfigOut,
    ChangePasswordIn,
    LoginIn,
    WhoAmIOut,
)
from vigilai.auth import accounts
from vigilai.auth.passwords import PasswordTooShort
from vigilai.auth.sessions import COOKIE_NAME, create_session, revoke_session
from vigilai.auth.settings import AuthSettings
from vigilai.db import repository

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

#: Starlette deprecated its 422 constant; the number is stable and the import is not.
HTTP_422: Final[int] = 422

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, request: Request, token: str, max_age: int) -> None:
    """Attach the session cookie.

    Args:
        response: The outgoing response.
        request: The incoming request, to tell whether it arrived over TLS.
        token: The session token.
        max_age: The cookie lifetime in seconds.

    ``Secure`` is set only when the request arrived over TLS, because a cookie marked
    secure on a plain-HTTP development server is never sent back and the sign-in
    silently fails.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.get("/config", response_model=AuthConfigOut)
def auth_config(settings: AuthSettings = Depends(get_auth_settings)) -> AuthConfigOut:
    """Which switches are on, so a UI knows whether to show a sign-in page.

    Args:
        settings: The authentication switches.

    Returns:
        The two switches. Public: it reveals nothing an unauthenticated caller could
        not learn by trying a request.
    """
    return AuthConfigOut(admin_auth=settings.admin_auth, user_auth=settings.user_auth)


@router.get("/me", response_model=WhoAmIOut)
def whoami(user: CurrentUser = Depends(current_user)) -> WhoAmIOut:
    """Who the caller is.

    Args:
        user: The caller.

    Returns:
        The current account, which is the placeholder when login is off.
    """
    return WhoAmIOut(
        id=user.id,
        username=user.username,
        name=user.name,
        email=user.email,
        role=user.role,
        is_admin=user.is_admin,
        is_placeholder=user.is_placeholder,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=WhoAmIOut)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> WhoAmIOut:
    """Sign in.

    Args:
        payload: The username and password.
        request: The incoming request.
        response: The outgoing response, which receives the cookie.
        session: The request's database session.
        settings: The authentication switches.

    Returns:
        The signed-in account, including whether a password change is outstanding.

    Raises:
        HTTPException: 401 for a wrong username or password, 423 while the account is
            locked. The two are distinguished because a lockout is something the
            person needs to be told about; which half of the credential was wrong is
            not.
    """
    try:
        user = accounts.authenticate(session, settings, payload.username, payload.password)
    except accounts.AccountLocked as exc:
        repository.audit(session, "auth.locked", detail=payload.username[:100])
        # Committed before raising: the dependency rolls the session back on any
        # exception, which would otherwise discard the failure counter and the audit
        # entry — and a lockout that forgets its own count is not a lockout.
        session.commit()
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
    except accounts.BadCredentials as exc:
        repository.audit(session, "auth.login_failed", detail=payload.username[:100])
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    token, _ = create_session(session, settings, user)
    _set_cookie(response, request, token, settings.session_ttl_s)
    repository.audit(session, "auth.login", detail=user.username, user_id=user.id, actor=user.name)
    _LOG.info("account %s signed in", user.id)
    return WhoAmIOut(
        id=user.id,
        username=user.username,
        name=user.name or user.username,
        email=user.email,
        role=user.role,
        is_admin=user.role == "admin",
        is_placeholder=False,
        must_change_password=user.must_change_password,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> None:
    """Sign out, ending the session on the server.

    Args:
        request: The incoming request, for its cookie.
        response: The outgoing response, which loses the cookie.
        session: The request's database session.
    """
    token = request.cookies.get(COOKIE_NAME, "")
    if revoke_session(session, token):
        repository.audit(session, "auth.logout")
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/change-password", response_model=WhoAmIOut)
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> WhoAmIOut:
    """Set a new password, which is how a first sign-in completes.

    The current password is re-checked here rather than trusting the session, because
    this is the one request that can change who can sign in.

    Args:
        payload: The username, the current password, and the new one.
        request: The incoming request.
        response: The outgoing response, which receives a fresh cookie.
        session: The request's database session.
        settings: The authentication switches.

    Returns:
        The account, with the change requirement cleared.

    Raises:
        HTTPException: 401 when the current password is wrong, 423 while locked, and
            422 when the new password is too short or is the one being replaced.
    """
    try:
        user = accounts.authenticate(session, settings, payload.username, payload.current_password)
    except accounts.AccountLocked as exc:
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
    except accounts.BadCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        accounts.set_password(session, settings, user, payload.new_password)
    except (PasswordTooShort, accounts.AccountError) as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    token, _ = create_session(session, settings, user)
    _set_cookie(response, request, token, settings.session_ttl_s)
    repository.audit(
        session, "auth.password_changed", detail=user.username, user_id=user.id, actor=user.name
    )
    return WhoAmIOut(
        id=user.id,
        username=user.username,
        name=user.name or user.username,
        email=user.email,
        role=user.role,
        is_admin=user.role == "admin",
        is_placeholder=False,
        must_change_password=False,
    )
