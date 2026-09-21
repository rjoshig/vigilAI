"""Wire models for the authentication endpoints (ADR-022).

A password is only ever an input. No response model here carries one, and none ever
should.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AuthConfigOut",
    "ChangePasswordIn",
    "LoginIn",
    "UserIn",
    "UserOut",
    "ResetPasswordIn",
    "WhoAmIOut",
]


class AuthConfigOut(BaseModel):
    """Which switches are on, so a UI knows whether to show a sign-in page."""

    admin_auth: bool = False
    user_auth: bool = False


class WhoAmIOut(BaseModel):
    """The current account."""

    id: int | None = None
    #: What was typed at the prompt. Returned so a screen that must re-authenticate,
    #: such as the forced password change after a page reload, does not have to ask
    #: the person who they are again.
    username: str = ""
    name: str = ""
    email: str = ""
    role: str = "user"
    #: Every role held, weakest first (ADR-049). ``role`` is the strongest of them and
    #: stays until everything reads this list.
    roles: list[str] = Field(default_factory=lambda: ["user"])
    #: What this caller may actually do, so **neither app has to know the matrix**
    #: (ADR-049). The matrix lives in one place and the apps read the answer: a console
    #: that reimplemented it would disagree with the API the first time a grant moved,
    #: and would disagree by showing a screen that then refuses.
    #:
    #: Empty for a plain user, and — while login is off — everything, because the
    #: placeholder holds `user` and `admin` and nothing is being enforced.
    capabilities: list[str] = Field(default_factory=list)
    is_admin: bool = False
    #: True when login is off and this is the stand-in every action is attributed to.
    is_placeholder: bool = False
    must_change_password: bool = False


class LoginIn(BaseModel):
    """A sign-in attempt."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    """A password change, which re-checks the current password."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class UserIn(BaseModel):
    """A new account, created by an administrator."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)
    role: str = "user"


class ResetPasswordIn(BaseModel):
    """An administrator setting someone else's password."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    """An account as the admin console sees it. Never carries a password."""

    id: int
    username: str
    name: str
    email: str
    role: str
    is_active: bool
    is_placeholder: bool
    must_change_password: bool
    last_login_at: str = ""
    locked: bool = False
    created_at: str = ""
