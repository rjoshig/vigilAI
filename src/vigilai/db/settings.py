"""Database configuration: one setting chooses the backend (ADR-017).

``DATABASE_URL`` selects SQLite or Postgres and nothing else in the code changes. SQLite
is the default so a test, a migration, or a single run needs no Docker; Postgres is what
``docker compose up`` configures, because SQLite takes one writer at a time.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["DbSettings", "Backend", "DEFAULT_URL"]

_LOG: Final = logging.getLogger(__name__)

Backend = Literal["sqlite", "postgresql"]

#: The default: a file beside the data directory, so nothing external is required.
DEFAULT_URL: Final[str] = "sqlite+pysqlite:///./data/vigilai.db"


class DbSettings(BaseModel):
    """Everything the data layer needs.

    Attributes:
        url: The SQLAlchemy URL. SQLite or Postgres.
        echo: Whether to log every statement. Off by default; statements can carry
            customer names, and logs hold ids and counts only (ADR-003).
        pool_size: Connections kept open. Ignored by SQLite, which has no pool worth
            tuning.
        data_dir: Where uploads, reports, and PDFs live. The shared volume in Docker.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = DEFAULT_URL
    echo: bool = False
    pool_size: int = Field(default=5, gt=0)
    data_dir: Path = Path("./data")

    @field_validator("url")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        """Reject a URL for a backend this project does not support.

        Args:
            value: The configured URL.

        Returns:
            The URL unchanged.

        Raises:
            ValueError: When the driver is neither SQLite nor Postgres. Failing here
                beats failing on the first query with a driver import error.
        """
        if not (value.startswith("sqlite") or value.startswith("postgresql")):
            raise ValueError(
                f"DATABASE_URL must be a sqlite or postgresql URL, got {value.split(':')[0]!r}"
            )
        return value

    @property
    def backend(self) -> Backend:
        """Which backend the URL selects.

        Returns:
            ``"sqlite"`` or ``"postgresql"``.
        """
        return "sqlite" if self.url.startswith("sqlite") else "postgresql"

    @property
    def is_sqlite(self) -> bool:
        """Whether this is the single-writer backend.

        Returns:
            ``True`` for SQLite. Callers use it to pick the row-claiming strategy, not to
            change behaviour that users can see.
        """
        return self.backend == "sqlite"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DbSettings:
        """Build settings from environment variables.

        Args:
            environ: The mapping to read, defaulting to ``os.environ``.

        Returns:
            The validated settings.
        """
        source = os.environ if environ is None else environ
        settings = cls(
            url=source.get("DATABASE_URL", DEFAULT_URL).strip() or DEFAULT_URL,
            echo=source.get("DB_ECHO", "false").strip().lower() in ("true", "1", "yes", "on"),
            pool_size=int(source.get("DB_POOL_SIZE", "5")),
            data_dir=Path(source.get("VIGILAI_DATA_DIR", "./data").strip() or "./data"),
        )
        _LOG.info("database backend: %s", settings.backend)
        return settings
