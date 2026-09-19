"""runtime settings and their change log

Two tables. app_settings holds overrides only, so a key nobody has touched keeps
following the environment (ADR-023). config_changes is append-only and carries the
old value as well as the new one, which is what makes "put it back" a button.

Revision ID: 71906528d2aa
Revises: baaae6a37f72
Created: 2026-09-18 17:22:40.584707

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import vigilai.db.types  # noqa: F401 - referenced by name in the column definitions
from sqlalchemy.dialects import postgresql
from sqlalchemy import Text

revision: str = "71906528d2aa"
down_revision: Union[str, None] = "baaae6a37f72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("updated_at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], name="fk_updated_by_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_app_settings_key"), ["key"], unique=True)

    op.create_table(
        "config_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column(
            "old_value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "new_value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"], name="fk_changed_by_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("config_changes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_config_changes_changed_at"), ["changed_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_config_changes_key"), ["key"], unique=False)


def downgrade() -> None:
    """Revert the change."""
    with op.batch_alter_table("config_changes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_config_changes_key"))
        batch_op.drop_index(batch_op.f("ix_config_changes_changed_at"))

    op.drop_table("config_changes")
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_app_settings_key"))

    op.drop_table("app_settings")
