"""Alembic environment.

The URL comes from ``DATABASE_URL`` so a migration runs against whichever backend is
configured (ADR-017). ``render_as_batch`` is on because SQLite cannot alter a column in
place; without it, any future column change would work on Postgres and fail on SQLite.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from greenlight_ai.db.models import Base
from greenlight_ai.db.settings import DbSettings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = DbSettings.from_env()
config.set_main_option("sqlalchemy.url", settings.url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without connecting, for review or for a DBA to apply."""
    context.configure(
        url=settings.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against the configured database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
