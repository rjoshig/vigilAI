"""Account administration (ADR-022, ADR-049).

Only an administrator reaches these routes, and they create every account: there is no
self-registration and no second place to administer people from. Accounts are
deactivated, never deleted, so what a person did stays attributed to them.

**Roles are a set.** An account holds any of ``user``, ``reviewer`` and ``admin``, and
its capabilities are the union, so granting one never takes another away.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Final

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from greenlight_ai.api.deps import CurrentUser, get_auth_settings, get_session, require_users
from greenlight_ai.api.schemas_auth import (
    ResetPasswordIn,
    RoleOut,
    RolesIn,
    UserIn,
    UserOut,
)
from greenlight_ai.auth import accounts
from greenlight_ai.auth.passwords import PasswordTooShort, hash_password
from greenlight_ai.auth.roles import ROLES, Role, describe, holds
from greenlight_ai.auth.sessions import revoke_all_for_user
from greenlight_ai.auth.settings import AuthSettings
from greenlight_ai.db import models, repository

__all__ = ["router"]

_LOG: Final = logging.getLogger(__name__)

#: Starlette deprecated its 422 constant; the number is stable and the import is not.
HTTP_422: Final[int] = 422

# Who has an account is the administrator's to decide, not a reviewer's.
router = APIRouter(prefix="/admin/users", tags=["admin"], dependencies=[Depends(require_users)])


def _out(row: models.User) -> UserOut:
    """Render an account for the admin console.

    Args:
        row: The account.

    Returns:
        The wire model, which never carries a password.
    """
    now = dt.datetime.now(dt.timezone.utc)
    return UserOut(
        id=row.id,
        username=row.username,
        name=row.name,
        email=row.email,
        roles=list(row.roles or []),
        is_active=row.is_active,
        is_placeholder=row.is_placeholder,
        must_change_password=row.must_change_password,
        last_login_at=row.last_login_at.isoformat() if row.last_login_at else "",
        locked=bool(row.locked_until and row.locked_until > now),
        created_at=row.created_at.isoformat(),
    )


def _get(session: Session, user_id: int) -> models.User:
    """Fetch an account or fail.

    Args:
        session: The request's session.
        user_id: The account id.

    Returns:
        The account.

    Raises:
        HTTPException: 404 when it does not exist.
    """
    row = session.get(models.User, user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {user_id} not found")
    return row


@router.get("/roles", response_model=list[RoleOut])
def list_roles() -> list[RoleOut]:
    """The three roles and what each is for, weakest first.

    Returns:
        One entry per role. The wording comes from ``auth/roles.py``, beside the grants
        it describes, so the console cannot say a role does something the matrix does
        not give it.
    """
    return [RoleOut(role=role, description=describe(role)) for role in ROLES]


@router.get("", response_model=list[UserOut])
def list_users(
    session: Session = Depends(get_session),
    _user: CurrentUser = Depends(require_users),
) -> list[UserOut]:
    """List every account, active or not.

    Args:
        session: The request's session.
        _user: The calling administrator.

    Returns:
        The accounts, administrators first, then by name.
    """
    accounts.ensure_placeholder(session)
    rows = session.execute(
        sa.select(models.User).order_by(models.User.is_placeholder, models.User.username)
    ).scalars()
    # Administrators first, then by name. Ordered here rather than in SQL because what
    # somebody holds is a JSON list now, and JSON membership is not portable across
    # SQLite and Postgres (ADR-017).
    return sorted(
        (_out(row) for row in rows),
        key=lambda out: (out.is_placeholder, Role.ADMIN.value not in out.roles, out.username),
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserIn,
    session: Session = Depends(get_session),
    settings: AuthSettings = Depends(get_auth_settings),
    user: CurrentUser = Depends(require_users),
) -> UserOut:
    """Create an account holding whichever roles it should.

    Args:
        payload: The account to create, including its first password.
        session: The request's session.
        settings: The authentication switches, for the password rules.
        user: The calling administrator.

    Returns:
        The new account, which must change its password at first sign-in.

    Raises:
        HTTPException: 422 when the username or email is taken, a role is unknown,
            or the first password is too short.
    """
    try:
        row = accounts.create_account(
            session,
            settings,
            username=payload.username,
            name=payload.name,
            email=payload.email,
            password=payload.password,
            roles=payload.roles,
            created_by=user.id,
        )
    except (accounts.AccountError, PasswordTooShort) as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    repository.audit(
        session,
        "admin.user_created",
        detail=f"{row.username} ({', '.join(row.roles or [])})",
        user_id=user.id,
        actor=user.name,
    )
    return _out(row)


@router.post("/{user_id}/password", response_model=UserOut)
def reset_password(
    user_id: int,
    payload: ResetPasswordIn,
    session: Session = Depends(get_session),
    settings: AuthSettings = Depends(get_auth_settings),
    user: CurrentUser = Depends(require_users),
) -> UserOut:
    """Set someone else's password, which they must then change.

    Args:
        user_id: The account.
        payload: The new password.
        session: The request's session.
        settings: The authentication switches.
        user: The calling administrator.

    Returns:
        The account.

    Raises:
        HTTPException: 404 when it does not exist, 422 when the password is too short
            or the target is the placeholder.
    """
    row = _get(session, user_id)
    if row.is_placeholder:
        raise HTTPException(
            HTTP_422,
            "the placeholder account cannot sign in, so it has no password",
        )
    try:
        # Not accounts.set_password: an administrator-set password must be changed by
        # the person, and it is not measured against what they had before.
        from greenlight_ai.auth.passwords import check_length

        check_length(payload.password, settings.min_password_length)
    except PasswordTooShort as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    row.password_hash = hash_password(payload.password)
    row.must_change_password = True
    row.failed_attempts = 0
    row.locked_until = None
    revoked = revoke_all_for_user(session, row.id)
    repository.audit(
        session,
        "admin.password_reset",
        detail=f"{row.username}, {revoked} session(s) ended",
        user_id=user.id,
        actor=user.name,
    )
    return _out(row)


@router.post("/{user_id}/active", response_model=UserOut)
def set_active(
    user_id: int,
    is_active: bool,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_users),
) -> UserOut:
    """Deactivate or reactivate an account.

    Deactivating ends its sessions at once, so the change takes effect immediately
    rather than at the next expiry.

    Args:
        user_id: The account.
        is_active: Whether it should be usable.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The account.

    Raises:
        HTTPException: 404 when it does not exist, 422 for the placeholder, and 409
            when it would leave no active administrator.
    """
    row = _get(session, user_id)
    if row.is_placeholder:
        raise HTTPException(
            HTTP_422,
            "the placeholder is how actions are attributed while login is off",
        )
    if not is_active and holds(row.roles, Role.ADMIN):
        # Counted in Python over the role list, because JSON membership is not portable
        # across SQLite and Postgres (ADR-017).
        if not accounts.other_active_admins(session, besides=row.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "this is the last active administrator; nobody could sign in afterwards",
            )

    row.is_active = is_active
    row.deactivated_at = None if is_active else dt.datetime.now(dt.timezone.utc)
    revoked = 0 if is_active else revoke_all_for_user(session, row.id)
    repository.audit(
        session,
        "admin.user_activated" if is_active else "admin.user_deactivated",
        detail=f"{row.username}, {revoked} session(s) ended",
        user_id=user.id,
        actor=user.name,
    )
    return _out(row)


@router.post("/{user_id}/roles", response_model=UserOut)
def set_roles(
    user_id: int,
    payload: RolesIn,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_users),
) -> UserOut:
    """Change which roles an account holds.

    Roles add up, so this is a set rather than a choice: saving ``user`` and
    ``reviewer`` grants the union of both, and saving nothing at all still leaves a
    plain ``user`` rather than an account locked out of everything.

    Args:
        user_id: The account.
        payload: The roles it should hold from now on.
        session: The request's session.
        user: The calling administrator.

    Returns:
        The account, with its roles as stored.

    Raises:
        HTTPException: 404 when it does not exist, 422 for the placeholder or an unknown
            role, and 409 when the change would leave the deployment with no
            administrator — including when it is the caller demoting themselves.
    """
    row = _get(session, user_id)
    before = list(row.roles or [])
    losing_admin = holds(before, Role.ADMIN) and not holds(payload.roles, Role.ADMIN)
    if losing_admin and not accounts.other_active_admins(session, besides=row.id):
        # Unrecoverable without a database edit, which is why it is refused rather than
        # warned about. It catches the caller demoting themselves as much as anybody
        # else: they are the last administrator either way.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this is the last administrator; nobody could reach the console afterwards",
        )

    try:
        held = accounts.set_roles(session, row, payload.roles)
    except accounts.AccountError as exc:
        raise HTTPException(HTTP_422, str(exc)) from exc

    repository.audit(
        session,
        "admin.user_roles_changed",
        detail=f"{row.username}: {', '.join(before) or 'nothing'} -> {', '.join(held)}",
        user_id=user.id,
        actor=user.name,
    )
    _LOG.info("account %s now holds %s", row.id, ", ".join(held))
    return _out(row)
