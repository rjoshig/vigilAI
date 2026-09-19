"""Column types that behave the same on SQLite and Postgres (ADR-017).

Portability is not free: a ``jsonb`` column and a naive timestamp both behave differently
across the two backends. Declaring the differences once, here, keeps every model free of
backend conditionals.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

__all__ = ["Json", "Utc", "utcnow"]

#: JSON that is indexable ``jsonb`` on Postgres and ordinary ``json`` on SQLite.
Json = sa.JSON().with_variant(JSONB, "postgresql")


def utcnow() -> dt.datetime:
    """Return the current time, timezone-aware.

    Returns:
        The current UTC time. Used as a column default so both backends store the same
        thing; SQLite has no native timestamp type and would otherwise keep whatever
        string it was handed.
    """
    return dt.datetime.now(dt.timezone.utc)


class Utc(TypeDecorator[dt.datetime]):
    """A timestamp that always comes back timezone-aware.

    Postgres with ``timezone=True`` returns an aware datetime; SQLite returns a naive
    one. Reading a stored time and getting a different type depending on the backend is
    the kind of difference that surfaces as a bug months later, so it is normalised here.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: Any) -> dt.datetime | None:
        """Normalise a value on the way in.

        Args:
            value: The datetime to store, or ``None``.
            dialect: The active dialect.

        Returns:
            The value as UTC, with a naive input assumed to be UTC already.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def process_result_value(self, value: dt.datetime | None, dialect: Any) -> dt.datetime | None:
        """Normalise a value on the way out.

        Args:
            value: The stored datetime, or ``None``.
            dialect: The active dialect.

        Returns:
            An aware UTC datetime.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
