"""Wire models for the runtime settings endpoints (ADR-023).

A secret is never carried outward. The console learns that one is set and its last
four characters, which is enough to recognise the right key and useless to anyone
who steals the response.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["SettingOut", "SettingIn", "SettingGroupOut", "ConfigChangeOut", "ProviderTestResult"]


class SettingOut(BaseModel):
    """One setting, its effective value, and the layer it came from."""

    key: str
    label: str
    group: str
    kind: str
    help: str
    #: ``admin``, ``env``, or ``default``. Showing this beside the value is what
    #: prevents the "why is this different from what is in .env" hour.
    source: str
    value: Any = None
    editable: bool = True
    restart: bool = False
    choices: Sequence[str] = ()
    minimum: int | None = None
    maximum: int | None = None
    #: For a secret only: whether one is configured, and its last four characters.
    is_set: bool = False
    last4: str = ""
    #: The value the environment or the built-in default would supply if the admin
    #: override were removed, so "revert" can say what it will revert to.
    fallback: Any = None
    fallback_source: str = "default"


class SettingGroupOut(BaseModel):
    """A section of the settings screen."""

    name: str
    settings: list[SettingOut] = Field(default_factory=list)


class SettingIn(BaseModel):
    """A change to one setting."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    #: The new value. For a secret this is the plaintext, encrypted before storage and
    #: never logged. Omit it and the current value is kept.
    value: Any = None


class ConfigChangeOut(BaseModel):
    """One entry in the settings change history."""

    id: int
    key: str
    old_value: Any = None
    new_value: Any = None
    changed_by: str = ""
    changed_at: dt.datetime


class ProviderTestResult(BaseModel):
    """What a connection test found."""

    ok: bool
    provider: str = ""
    model: str = ""
    detail: str = ""
    latency_ms: int = 0
