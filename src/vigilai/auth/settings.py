"""Authentication settings, read from the environment only (ADR-022).

Two independent switches, because the admin console and the user app are separate
deployments with different exposure. Both default to false, so a checkout behaves as it
always did.
"""

from __future__ import annotations

import logging
import os
from typing import Final, Mapping

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AuthSettings",
    "BOOTSTRAP_USERNAME",
    "BOOTSTRAP_PASSWORD",
    "PLACEHOLDER_EMAIL",
    "PLACEHOLDER_NAME",
    "LOOPBACK_HOSTS",
]

_LOG: Final = logging.getLogger(__name__)

#: The bootstrap administrator. Documented, therefore public knowledge, therefore it
#: must be changed at first sign-in and must not survive into a real deployment.
BOOTSTRAP_USERNAME: Final[str] = "admin"
BOOTSTRAP_PASSWORD: Final[str] = "admin123"

#: The account every action is attributed to while login is off. It reads as "no login
#: was enabled", never as a claim that a person did something.
PLACEHOLDER_NAME: Final[str] = "John Doe"
PLACEHOLDER_EMAIL: Final[str] = "jdoe@jdoe.com"

#: Bind addresses that count as a laptop rather than a deployment.
LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset(
    {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}
)


def _flag(source: Mapping[str, str], name: str, default: str = "false") -> bool:
    """Read a boolean environment variable.

    Args:
        source: The mapping to read.
        name: The variable name.
        default: What to assume when it is absent.

    Returns:
        Whether the value is one of the affirmative spellings.
    """
    return source.get(name, default).strip().lower() in ("true", "1", "yes", "on")


class AuthSettings(BaseModel):
    """Everything authentication needs.

    Attributes:
        admin_auth: Whether the admin console and ``/admin/*`` require a sign-in.
        user_auth: Whether the user app and the rest of the API require one.
        session_ttl_s: Absolute session lifetime. Eight hours: a working day, and not
            a session left open overnight on a shared machine.
        idle_ttl_s: How long a session may go unused before it stops working.
        min_password_length: The only password composition rule. Complexity classes and
            forced expiry push people toward predictable passwords, so neither exists.
        lockout_threshold: Consecutive failures before an account is locked.
        lockout_s: How long the lock lasts before it clears itself.
        bind_host: What the server binds to. Used for one check: refusing to serve a
            non-loopback deployment while the bootstrap password is unchanged. It has
            to be told, because the process cannot ask uvicorn after the fact.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    admin_auth: bool = False
    user_auth: bool = False
    session_ttl_s: int = Field(default=8 * 60 * 60, gt=0)
    idle_ttl_s: int = Field(default=60 * 60, gt=0)
    min_password_length: int = Field(default=12, ge=8)
    lockout_threshold: int = Field(default=5, gt=0)
    lockout_s: int = Field(default=15 * 60, gt=0)
    bind_host: str = "127.0.0.1"

    @property
    def enabled(self) -> bool:
        """Whether either switch is on.

        Returns:
            ``True`` when at least one app requires a sign-in.
        """
        return self.admin_auth or self.user_auth

    @property
    def is_loopback(self) -> bool:
        """Whether the server is bound to the local machine only.

        Returns:
            ``True`` for a laptop install, which is exempt from the bootstrap-password
            refusal.
        """
        return self.bind_host.strip().lower() in LOOPBACK_HOSTS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AuthSettings:
        """Build settings from environment variables.

        Args:
            environ: The mapping to read, defaulting to ``os.environ``.

        Returns:
            The validated settings.
        """
        source = os.environ if environ is None else environ
        settings = cls(
            admin_auth=_flag(source, "VIGILAI_ADMIN_AUTH"),
            user_auth=_flag(source, "VIGILAI_USER_AUTH"),
            session_ttl_s=int(source.get("VIGILAI_SESSION_TTL_S", str(8 * 60 * 60))),
            idle_ttl_s=int(source.get("VIGILAI_SESSION_IDLE_S", str(60 * 60))),
            min_password_length=int(source.get("VIGILAI_MIN_PASSWORD_LENGTH", "12")),
            lockout_threshold=int(source.get("VIGILAI_LOCKOUT_THRESHOLD", "5")),
            lockout_s=int(source.get("VIGILAI_LOCKOUT_S", str(15 * 60))),
            bind_host=source.get("VIGILAI_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1",
        )
        if settings.user_auth and not settings.admin_auth:
            _LOG.warning(
                "user login is on but admin login is off: the admin console is open to "
                "anyone who can reach it"
            )
        _LOG.info("authentication: admin=%s user=%s", settings.admin_auth, settings.user_auth)
        return settings
