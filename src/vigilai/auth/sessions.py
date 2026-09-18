"""Server-side sessions (ADR-022).

A session is a row, not a self-contained token, because revoking one and knowing who
is signed in both matter more here than saving a database read. Only a hash of the
token is stored, so the table is a set of references rather than a set of working
credentials.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
from typing import Final, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import Session

from vigilai.auth.settings import AuthSettings
from vigilai.db import models

__all__ = [
    "COOKIE_NAME",
    "create_session",
    "resolve_session",
    "revoke_session",
    "revoke_all_for_user",
    "purge_expired_sessions",
    "token_hash",
]

_LOG: Final = logging.getLogger(__name__)

#: The cookie both apps send. It holds the token and nothing else.
COOKIE_NAME: Final[str] = "vigilai_session"

_TOKEN_BYTES: Final[int] = 32


def token_hash(token: str) -> str:
    """Hash a session token for storage and lookup.

    Args:
        token: The token from the cookie.

    Returns:
        Its SHA-256 hex digest. A plain hash is right here, unlike for a password: the
        token is 256 random bits, so there is nothing to guess and nothing to salt.
    """
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(
    session: Session, settings: AuthSettings, user: models.User, origin: str = "password"
) -> Tuple[str, models.UserSession]:
    """Start a session for an account.

    Args:
        session: An open session.
        settings: Authentication settings, for the lifetime.
        user: The account signing in.
        origin: How it was established. ``password`` today; an external identity
            provider would set its own value here.

    Returns:
        The token to put in the cookie, and the stored row. The token is returned
        once and never stored, so it cannot be read back out of the database.
    """
    now = dt.datetime.now(dt.timezone.utc)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    row = models.UserSession(
        token_hash=token_hash(token),
        user_id=user.id,
        origin=origin,
        created_at=now,
        last_seen_at=now,
        expires_at=now + dt.timedelta(seconds=settings.session_ttl_s),
    )
    session.add(row)
    session.flush()
    return token, row


def resolve_session(session: Session, settings: AuthSettings, token: str) -> models.User | None:
    """Look up the account behind a cookie, and keep the session alive.

    Args:
        session: An open session.
        settings: Authentication settings, for the idle timeout.
        token: The token from the cookie.

    Returns:
        The account, or ``None`` when the session is unknown, revoked, expired, idle
        too long, or belongs to an account that has since been deactivated. An expired
        or idle session is revoked on the way out, so it cannot come back.
    """
    if not token:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    row = session.execute(
        sa.select(models.UserSession).where(models.UserSession.token_hash == token_hash(token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None

    idle_deadline = row.last_seen_at + dt.timedelta(seconds=settings.idle_ttl_s)
    if row.expires_at <= now or idle_deadline <= now:
        row.revoked_at = now
        session.flush()
        return None

    user = session.get(models.User, row.user_id)
    if user is None or not user.is_active or user.is_placeholder:
        row.revoked_at = now
        session.flush()
        return None

    row.last_seen_at = now
    session.flush()
    return user


def revoke_session(session: Session, token: str) -> bool:
    """End one session.

    Args:
        session: An open session.
        token: The token from the cookie.

    Returns:
        Whether a live session was ended.
    """
    row = session.execute(
        sa.select(models.UserSession).where(models.UserSession.token_hash == token_hash(token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = dt.datetime.now(dt.timezone.utc)
    session.flush()
    return True


def revoke_all_for_user(session: Session, user_id: int) -> int:
    """End every session an account holds.

    Args:
        session: An open session.
        user_id: The account.

    Returns:
        How many sessions were ended. Deactivating an account does this, so the change
        takes effect immediately rather than at the next expiry.
    """
    now = dt.datetime.now(dt.timezone.utc)
    live = list(
        session.execute(
            sa.select(models.UserSession).where(
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None),
            )
        ).scalars()
    )
    for row in live:
        row.revoked_at = now
    session.flush()
    return len(live)


def purge_expired_sessions(session: Session) -> int:
    """Delete sessions that ended long enough ago to be of no interest.

    Args:
        session: An open session.

    Returns:
        How many rows were removed. Called by the retention sweep; a revoked session
        is already useless, so this is housekeeping rather than a control.
    """
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
    stale = list(
        session.execute(
            sa.select(models.UserSession).where(models.UserSession.expires_at < cutoff)
        ).scalars()
    )
    for row in stale:
        session.delete(row)
    session.flush()
    return len(stale)
