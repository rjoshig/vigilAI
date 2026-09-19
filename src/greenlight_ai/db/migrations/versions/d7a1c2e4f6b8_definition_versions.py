"""definition versions with revert

Every save of an artifact type or a programme's rule set keeps a snapshot; ten are
listed, a revert is a new version, and a run records which versions it was
processed under (Phase 6.8c, ADR-029).

Revision ID: d7a1c2e4f6b8
Revises: b614b77ca9d8
Created: 2026-09-19 18:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

import greenlight_ai.db.types  # noqa: F401 - referenced by name in the column definitions

revision: str = "d7a1c2e4f6b8"
down_revision: Union[str, None] = "b614b77ca9d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "definition_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("object_key", sa.String(length=60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("reverted_from", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", greenlight_ai.db.types.Utc(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "object_key", "version", name="uq_definition_version"),
    )
    with op.batch_alter_table("definition_versions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_definition_versions_kind"), ["kind"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_definition_versions_object_key"), ["object_key"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_definition_versions_created_at"), ["created_at"], unique=False
        )

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "definition_versions",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade() -> None:
    """Undo the change."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("definition_versions")
    with op.batch_alter_table("definition_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_definition_versions_created_at"))
        batch_op.drop_index(batch_op.f("ix_definition_versions_object_key"))
        batch_op.drop_index(batch_op.f("ix_definition_versions_kind"))
    op.drop_table("definition_versions")
