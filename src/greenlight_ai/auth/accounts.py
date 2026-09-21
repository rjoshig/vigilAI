"""Accounts: the placeholder, the bootstrap administrator, and everything after.

No self-registration anywhere. An administrator creates every account, for both roles
(ADR-022). Accounts are deactivated, never deleted, so what a person did stays
attributed to them.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Final, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai.auth.passwords import check_length, hash_password, verify_password
from greenlight_ai.auth.roles import ROLES, Role, holds, normalize_roles
from greenlight_ai.auth.settings import (
    BOOTSTRAP_PASSWORD,
    BOOTSTRAP_USERNAME,
    PLACEHOLDER_EMAIL,
    PLACEHOLDER_NAME,
    AuthSettings,
)
from greenlight_ai.db import models

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
    "other_active_admins",
    "set_password",
    "set_roles",
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


def _real_admins(session: Session) -> list[models.User]:
    """Every account that holds ``admin`` and is not the placeholder.

    Args:
        session: An open session.

    Returns:
        The rows, which may be empty on a fresh install.

    Membership of the stored role list is tested in Python rather than in SQL. A JSON
    containment predicate is written differently on SQLite and on Postgres and the
    product must run unchanged on both (ADR-017); the users table is the smallest in
    the schema, so reading it whole is cheaper than the portability problem.
    """
    rows = session.execute(
        sa.select(models.User).where(sa.not_(models.User.is_placeholder))
    ).scalars()
    return [row for row in rows if holds(row.roles, Role.ADMIN)]


def other_active_admins(session: Session, *, besides: int) -> int:
    """How many active administrators there would still be without this one.

    Args:
        session: An open session.
        besides: The account being deactivated or demoted.

    Returns:
        The count of other active, non-placeholder accounts holding ``admin``. Zero
        means the change would lock everybody out of the console, which is only
        recoverable by editing the database.
    """
    return sum(1 for row in _real_admins(session) if row.is_active and row.id != besides)


def ensure_placeholder(session: Session) -> models.User:
    """Create or fetch the account used while login is off.

    Args:
        session: An open session.

    Returns:
        The placeholder. It is a real row so every action has a real author, and it
        carries no usable password, so it can never be signed in as.

        It holds **user and admin** (ADR-049). While login is off this is the only
        account there is and it can already do everything, so the stored roles say what
        the behaviour already is and the console does not refuse the only account there
        is now that it gates on them.
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
        roles=[Role.USER.value, Role.ADMIN.value],
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
    if _real_admins(session):
        return None

    row = models.User(
        username=BOOTSTRAP_USERNAME,
        name="Administrator",
        email="admin@localhost",
        password_hash=hash_password(BOOTSTRAP_PASSWORD),
        roles=[Role.USER.value, Role.ADMIN.value],
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
    roles: Sequence[str],
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
        roles: Which of ``user``, ``reviewer`` and ``admin`` this person holds. They add
            up, so a senior associate is a user *and* a reviewer.
        created_by: The administrator's user id.

    Returns:
        The new account.

    Raises:
        AccountError: When the username or email is taken, a role is unknown, or the
            username is reserved.
        PasswordTooShort: When the first password is below the minimum length.
    """
    username = username.strip().lower()
    email = email.strip().lower()
    unknown = [role for role in roles if role not in ROLES]
    if unknown:
        raise AccountError(f"{unknown[0]!r} is not a role; use any of {', '.join(ROLES)}")
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

    held = normalize_roles(roles)
    row = models.User(
        username=username,
        name=name.strip(),
        email=email,
        password_hash=hash_password(password),
        roles=list(held),
        must_change_password=True,
        created_by_user_id=created_by,
    )
    session.add(row)
    session.flush()
    _LOG.info("account %s created holding %s", row.id, ", ".join(held))
    return row


def set_roles(session: Session, user: models.User, roles: Sequence[str]) -> tuple[str, ...]:
    """Change which roles an account holds.

    Args:
        session: An open session.
        user: The account.
        roles: What it should hold from now on.

    Returns:
        The roles as stored, weakest first.

    Raises:
        AccountError: When a name is not a role, or when the account is the placeholder,
            whose roles are what keeps the product working with login off.
    """
    if user.is_placeholder:
        raise AccountError(
            "the placeholder holds user and admin because that is how the product "
            "behaves with login off; changing it would gate the only account there is"
        )
    unknown = [role for role in roles if role not in ROLES]
    if unknown:
        raise AccountError(f"{unknown[0]!r} is not a role; use any of {', '.join(ROLES)}")

    held = normalize_roles(roles)
    user.roles = list(held)
    session.flush()
    return held


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
