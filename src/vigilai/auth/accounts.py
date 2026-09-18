"""Accounts: the placeholder, the bootstrap administrator, and everything after.

No self-registration anywhere. An administrator creates every account, for both roles
(ADR-022). Accounts are deactivated, never deleted, so what a person did stays
attributed to them.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Final

import sqlalchemy as sa
from sqlalchemy.orm import Session

from vigilai.auth.passwords import check_length, hash_password, verify_password
from vigilai.auth.settings import (
    BOOTSTRAP_PASSWORD,
    BOOTSTRAP_USERNAME,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_NAME,
    AuthSettings,
)
from vigilai.db import models

__all__ = [
    "AccountError",
    "AccountLocked",
    "BadCredentials",
    "DefaultPasswordInUse",
    "PLACEHOLDER_USERNAME",
    "authenticate",
    "bootstrap_admin_uses_default_password",
    "create_account",
    "ensure_bootstrap",
    "ensure_placeholder",
    "set_password",
]

_LOG: Final = logging.getLogger(__name__)

#: The placeholder's username. Reserved: nothing may sign in as it.
PLACEHOLDER_USERNAME: Final[str] = "__placeholder__"


class AccountError(Exception):
    """A problem with an account operation that the caller should report."""


class BadCredentials(AccountError):
    """The username is unknown, the password is wrong, or the account is inactive.

    One exception for all three on purpose: telling a stranger which of them is true
    tells them whether an account exists.
    """


class AccountLocked(AccountError):
    """Too many consecutive failures; the account is locked for a cooling-off period."""


class DefaultPasswordInUse(AccountError):
    """The bootstrap administrator still has the documented default password."""


def ensure_placeholder(session: Session) -> models.User:
    """Create or fetch the account used while login is off.

    Args:
        session: An open session.

    Returns:
        The placeholder. It is a real row so every action has a real author, and it
        carries no usable password, so it can never be signed in as.
    """
    row = session.execute(
        sa.select(models.User).where(models.User.is_placeholder)
    ).scalar_one_or_none()
    if row is not None:
        return row

    row = models.User(
        username=PLACEHOLDER_USERNAME,
        name=PLACEHOLDER_NAME,
        email=PLACEHOLDER_EMAIL,
        password_hash="",
        role="user",
        is_placeholder=True,
        is_active=True,
    )
    session.add(row)
    session.flush()
    _LOG.info("seeded the placeholder account used while login is off")
    return row


def ensure_bootstrap(session: Session) -> models.User | None:
    """Create the first administrator when there is none.

    Args:
        session: An open session.

    Returns:
        The account it created, or ``None`` when an administrator already exists.

    The password is the documented default and the account must change it before it
    can do anything else. This is a way into a fresh install, not a credential.
    """
    existing = session.execute(
        sa.select(models.User).where(
            models.User.role == "admin", sa.not_(models.User.is_placeholder)
        )
    ).first()
    if existing is not None:
        return None

    row = models.User(
        username=BOOTSTRAP_USERNAME,
        name="Administrator",
        email="admin@localhost",
        password_hash=hash_password(BOOTSTRAP_PASSWORD),
        role="admin",
        must_change_password=True,
        is_active=True,
    )
    session.add(row)
    session.flush()
    _LOG.warning(
        "created the bootstrap administrator %r with the documented default password; "
        "it must be changed at first sign-in",
        BOOTSTRAP_USERNAME,
    )
    return row


def bootstrap_admin_uses_default_password(session: Session) -> bool:
    """Whether the documented default is still in force.

    Args:
        session: An open session.

    Returns:
        ``True`` when an active ``admin`` account still verifies against the default
        password. Checked at startup, because a deployment that is not on loopback
        must not serve while it is true.
    """
    row = session.execute(
        sa.select(models.User).where(models.User.username == BOOTSTRAP_USERNAME)
    ).scalar_one_or_none()
    if row is None or not row.is_active:
        return False
    return verify_password(BOOTSTRAP_PASSWORD, row.password_hash)


def create_account(
    session: Session,
    settings: AuthSettings,
    *,
    username: str,
    name: str,
    email: str,
    password: str,
    role: str,
    created_by: int | None,
) -> models.User:
    """Create an account, which only an administrator may do.

    Args:
        session: An open session.
        settings: Authentication settings, for the password rules.
        username: What is typed at the prompt.
        name: The person's name.
        email: Their address.
        password: The first password, which they must change at first sign-in.
        role: ``admin`` or ``user``.
        created_by: The administrator's user id.

    Returns:
        The new account.

    Raises:
        AccountError: When the username or email is taken, the role is unknown, or the
            username is reserved.
        PasswordTooShort: When the first password is below the minimum length.
    """
    username = username.strip().lower()
    email = email.strip().lower()
    if role not in ("admin", "user"):
        raise AccountError(f"{role!r} is not a role; use 'admin' or 'user'")
    if not username or username == PLACEHOLDER_USERNAME:
        raise AccountError("that username is reserved")
    check_length(password, settings.min_password_length)

    clash = session.execute(
        sa.select(models.User).where(
            sa.or_(models.User.username == username, models.User.email == email)
        )
    ).first()
    if clash is not None:
        raise AccountError("that username or email is already in use")

    row = models.User(
        username=username,
        name=name.strip(),
        email=email,
        password_hash=hash_password(password),
        role=role,
        must_change_password=True,
        created_by_user_id=created_by,
    )
    session.add(row)
    session.flush()
    _LOG.info("account %s created with role %s", row.id, role)
    return row


def set_password(
    session: Session, settings: AuthSettings, user: models.User, password: str
) -> None:
    """Set an account's password and clear the change requirement.

    Args:
        session: An open session.
        settings: Authentication settings, for the minimum length.
        user: The account.
        password: The new password.

    Raises:
        AccountError: When the new password is the one being replaced.
        PasswordTooShort: When it is below the minimum length.
    """
    check_length(password, settings.min_password_length)
    if verify_password(password, user.password_hash):
        raise AccountError("the new password must differ from the current one")
    user.password_hash = hash_password(password)
    user.must_change_password = False
    user.failed_attempts = 0
    user.locked_until = None
    session.flush()


def authenticate(
    session: Session, settings: AuthSettings, username: str, password: str
) -> models.User:
    """Check a sign-in.

    Args:
        session: An open session.
        settings: Authentication settings, for the lockout rules.
        username: What was typed.
        password: What was typed.

    Returns:
        The account.

    Raises:
        AccountLocked: When the account is inside its cooling-off period.
        BadCredentials: When the username is unknown, the account is inactive or the
            placeholder, or the password is wrong.
    """
    now = dt.datetime.now(dt.timezone.utc)
    row = session.execute(
        sa.select(models.User).where(models.User.username == username.strip().lower())
    ).scalar_one_or_none()

    if row is None or row.is_placeholder or not row.is_active:
        raise BadCredentials("the username or password is wrong")
    if row.locked_until is not None and row.locked_until > now:
        raise AccountLocked("too many failed attempts; try again shortly")

    if not verify_password(password, row.password_hash):
        row.failed_attempts += 1
        if row.failed_attempts >= settings.lockout_threshold:
            row.locked_until = now + dt.timedelta(seconds=settings.lockout_s)
            _LOG.warning("account %s locked after %d failures", row.id, row.failed_attempts)
        session.flush()
        raise BadCredentials("the username or password is wrong")

    row.failed_attempts = 0
    row.locked_until = None
    row.last_login_at = now
    session.flush()
    return row
