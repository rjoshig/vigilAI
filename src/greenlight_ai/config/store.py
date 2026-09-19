"""Resolving a setting across its three layers (ADR-023).

**Admin console, then the environment, then the built-in default.** The table holds
overrides only, so a key nobody has touched behaves exactly as it did when the
environment was the only source.

Two rules keep this honest:

- **Nothing is read at import time.** A module-level constant is fixed for the life of
  the process, which is the usual reason a runtime setting turns out not to be one.
  Every value is read through :func:`resolve` at the point it is used.
- **A secret never comes back out.** :func:`effective` reports that one is set and
  its last four characters. Only :func:`read_secret` decrypts, and only the adapter
  calls it.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Final, Literal, Mapping

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from greenlight_ai.config import secrets
from greenlight_ai.config.registry import SETTINGS_BY_KEY, SettingSpec
from greenlight_ai.db import models

__all__ = [
    "Resolved",
    "Source",
    "CACHE_TTL_S",
    "effective",
    "fallback",
    "invalidate",
    "read_secret",
    "resolve",
    "write_setting",
    "clear_setting",
]

_LOG: Final = logging.getLogger(__name__)

Source = Literal["admin", "env", "default"]

#: How stale a value may be in a process that did not make the change. The api and the
#: worker are separate processes reading the same table, so one of them will always
#: learn about an edit a moment late; five seconds is under the time it takes to
#: switch windows and look. A write invalidates the writer's own cache immediately.
CACHE_TTL_S: Final[float] = 5.0

_TRUE: Final[frozenset[str]] = frozenset({"true", "1", "yes", "on"})
_FALSE: Final[frozenset[str]] = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class Resolved:
    """A setting's effective value and where it came from.

    Attributes:
        spec: The registry entry.
        value: The effective value, already coerced to the declared type. For a
            secret this is the empty string; secrets are read through
            :func:`read_secret`.
        source: Which layer supplied it.
        is_set: For a secret, whether one is stored or configured at all.
        last4: For a secret, its last four characters, so the console can show that
            the right one is in place without showing it.
    """

    spec: SettingSpec
    value: Any
    source: Source
    is_set: bool = False
    last4: str = ""


class _Cache:
    """The per-process override cache.

    Attributes:
        rows: The last read of the overrides table.
        at: When it was read.
    """

    __slots__ = ("rows", "at", "lock")

    def __init__(self) -> None:
        """Start empty, so the first read always goes to the database."""
        self.rows: dict[str, tuple[Any, bool]] = {}
        self.at: float = 0.0
        self.lock = threading.Lock()


_CACHE: Final[_Cache] = _Cache()


def invalidate() -> None:
    """Drop the cached overrides.

    Called after every write so the process that made a change sees it at once, and
    available to a test that wants no staleness at all.
    """
    with _CACHE.lock:
        _CACHE.at = 0.0


def _overrides(session: Session) -> dict[str, tuple[Any, bool]]:
    """The stored overrides, from cache when it is fresh enough.

    Args:
        session: An open session.

    Returns:
        Key to (value, is_secret).

    A database error returns the last known good cache rather than failing the
    request: a settings table that is briefly unreachable should not take down a run
    that was going to use the defaults anyway.
    """
    now = time.monotonic()
    with _CACHE.lock:
        if _CACHE.at and now - _CACHE.at < CACHE_TTL_S:
            return dict(_CACHE.rows)

    try:
        rows = {
            str(row.key): (row.value, bool(row.is_secret))
            for row in session.execute(sa.select(models.AppSetting)).scalars()
        }
    except SQLAlchemyError:
        _LOG.warning("could not read the settings table; using the last known values")
        with _CACHE.lock:
            return dict(_CACHE.rows)

    with _CACHE.lock:
        _CACHE.rows = rows
        _CACHE.at = now
    return dict(rows)


def _coerce(spec: SettingSpec, raw: Any) -> Any:
    """Turn a stored or environment value into the declared type.

    Args:
        spec: The registry entry.
        raw: The value as stored or as read from the environment.

    Returns:
        The typed value, or the default when it cannot be read as the declared type.
        A malformed value must not take the service down; it is reported and ignored.
    """
    try:
        if spec.kind == "bool":
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().lower()
            if text in _TRUE:
                return True
            if text in _FALSE:
                return False
            raise ValueError(text)
        if spec.kind == "int":
            value = int(raw)
            if spec.minimum is not None and value < spec.minimum:
                raise ValueError(f"{value} < {spec.minimum}")
            if spec.maximum is not None and value > spec.maximum:
                raise ValueError(f"{value} > {spec.maximum}")
            return value
        if spec.kind == "enum":
            text = str(raw).strip()
            if spec.choices and text not in spec.choices:
                raise ValueError(text)
            return text
        return str(raw)
    except (TypeError, ValueError) as exc:
        _LOG.warning("ignoring an unusable value for %s (%s)", spec.key, exc)
        return spec.default


def resolve(session: Session, key: str, environ: Mapping[str, str] | None = None) -> Resolved:
    """Work out one setting's effective value.

    Args:
        session: An open session.
        key: The registry key.
        environ: The environment to read, defaulting to the real one.

    Returns:
        The value and the layer it came from.

    Raises:
        KeyError: When the key is not in the registry. Every setting is declared in
            one place so the console and the code cannot disagree about what exists.
    """
    spec = SETTINGS_BY_KEY[key]
    source_env = os.environ if environ is None else environ
    stored = _overrides(session).get(key) if spec.editable else None

    if spec.kind == "secret":
        if stored is not None and stored[0]:
            plain = secrets.decrypt(str(stored[0]), environ)
            if plain:
                return Resolved(spec, "", "admin", is_set=True, last4=secrets.last4(plain))
        from_env = source_env.get(spec.env, "").strip()
        if from_env:
            return Resolved(spec, "", "env", is_set=True, last4=secrets.last4(from_env))
        return Resolved(spec, "", "default", is_set=False)

    if stored is not None and stored[0] is not None:
        return Resolved(spec, _coerce(spec, stored[0]), "admin")

    raw = source_env.get(spec.env)
    if raw is not None and str(raw).strip() != "":
        return Resolved(spec, _coerce(spec, raw), "env")

    return Resolved(spec, spec.default, "default")


def fallback(key: str, environ: Mapping[str, str] | None = None) -> Resolved:
    """What a setting would be if its admin override were removed.

    Args:
        key: The registry key.
        environ: The environment to read.

    Returns:
        The resolution from the environment and the built-in default alone. The
        console shows this beside the effective value so "revert" can say what it
        will revert to rather than asking the administrator to guess.

    Raises:
        KeyError: When the key is unknown.
    """
    spec = SETTINGS_BY_KEY[key]
    source_env = os.environ if environ is None else environ
    if spec.kind == "secret":
        from_env = source_env.get(spec.env, "").strip()
        return Resolved(
            spec,
            "",
            "env" if from_env else "default",
            is_set=bool(from_env),
            last4=secrets.last4(from_env),
        )
    raw = source_env.get(spec.env)
    if raw is not None and str(raw).strip() != "":
        return Resolved(spec, _coerce(spec, raw), "env")
    return Resolved(spec, spec.default, "default")


def effective(session: Session, environ: Mapping[str, str] | None = None) -> list[Resolved]:
    """Every setting, its effective value, and its layer.

    Args:
        session: An open session.
        environ: The environment to read.

    Returns:
        One entry per registry setting, in declaration order. This is what the
        console's read-only view shows, and seeing the layer beside the value is what
        prevents the "why is this different from what is in .env" hour.
    """
    return [resolve(session, key, environ) for key in SETTINGS_BY_KEY]


def read_secret(session: Session, key: str, environ: Mapping[str, str] | None = None) -> str:
    """Decrypt a stored secret, or fall back to the environment.

    Args:
        session: An open session.
        key: The registry key.
        environ: The environment to read.

    Returns:
        The secret, or an empty string when none is configured. Only the adapter
        calls this; nothing returns it to a client.

    Raises:
        KeyError: When the key is unknown.
        ValueError: When the key is not declared as a secret, which would mean a
            caller is reaching for the wrong thing.
    """
    spec = SETTINGS_BY_KEY[key]
    if spec.kind != "secret":
        raise ValueError(f"{key} is not a secret")
    stored = _overrides(session).get(key)
    if stored is not None and stored[0]:
        plain = secrets.decrypt(str(stored[0]), environ)
        if plain:
            return plain
    source_env = os.environ if environ is None else environ
    return source_env.get(spec.env, "").strip()


def write_setting(
    session: Session,
    key: str,
    value: Any,
    *,
    user_id: int | None = None,
    actor: str = "",
    environ: Mapping[str, str] | None = None,
) -> Resolved:
    """Store an override and record the change.

    Args:
        session: An open session.
        key: The registry key.
        value: The new value. For a secret this is the plaintext, encrypted here and
            never stored or logged in the clear.
        user_id: Who changed it.
        actor: Their display name.
        environ: The environment, for the master key and for resolving afterwards.

    Returns:
        The setting as it now resolves.

    Raises:
        KeyError: When the key is unknown.
        ValueError: When the setting is not editable at runtime, or the value is not
            valid for its declared type.
        SecretsUnavailable: When a secret is offered and no master key is configured.
    """
    spec = SETTINGS_BY_KEY[key]
    if not spec.editable:
        raise ValueError(f"{key} is not editable at runtime: {spec.help}")

    if spec.kind == "secret":
        stored_value: Any = secrets.encrypt(str(value), environ)
    else:
        coerced = _coerce(spec, value)
        if coerced != value and str(coerced) != str(value):
            raise ValueError(f"{value!r} is not a valid {spec.kind} for {key}")
        stored_value = coerced

    before = resolve(session, key, environ)
    row = session.execute(
        sa.select(models.AppSetting).where(models.AppSetting.key == key)
    ).scalar_one_or_none()
    if row is None:
        row = models.AppSetting(key=key, is_secret=spec.kind == "secret")
        session.add(row)
    row.value = stored_value
    row.is_secret = spec.kind == "secret"
    row.updated_by_user_id = user_id
    row.updated_by = actor[:200]

    session.add(
        models.ConfigChange(
            key=key,
            # A secret's values are never recorded, only that it changed.
            old_value="(secret)" if spec.kind == "secret" else before.value,
            new_value="(secret)" if spec.kind == "secret" else stored_value,
            changed_by_user_id=user_id,
            changed_by=actor[:200],
        )
    )
    session.flush()
    invalidate()
    _LOG.info("setting %s changed by %s", key, actor or "an administrator")
    return resolve(session, key, environ)


def clear_setting(
    session: Session,
    key: str,
    *,
    user_id: int | None = None,
    actor: str = "",
    environ: Mapping[str, str] | None = None,
) -> Resolved:
    """Remove an override, so the setting falls back to the environment.

    Args:
        session: An open session.
        key: The registry key.
        user_id: Who cleared it.
        actor: Their display name.
        environ: The environment, for resolving afterwards.

    Returns:
        The setting as it now resolves, which is the layer beneath.

    Raises:
        KeyError: When the key is unknown.
    """
    spec = SETTINGS_BY_KEY[key]
    before = resolve(session, key, environ)
    row = session.execute(
        sa.select(models.AppSetting).where(models.AppSetting.key == key)
    ).scalar_one_or_none()
    if row is not None:
        session.delete(row)
        session.add(
            models.ConfigChange(
                key=key,
                old_value="(secret)" if spec.kind == "secret" else before.value,
                new_value=None,
                changed_by_user_id=user_id,
                changed_by=actor[:200],
            )
        )
        session.flush()
        invalidate()
        _LOG.info("setting %s cleared by %s", key, actor or "an administrator")
    return resolve(session, key, environ)
