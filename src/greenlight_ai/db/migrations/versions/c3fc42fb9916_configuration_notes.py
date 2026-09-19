"""configuration notes

A standing note on an ETL configuration is an observation of kind config_note with
the configuration it follows, and a run keeps a copy of the notes in force when it
was submitted (ADR-024). Every new column carries a server default an existing row
satisfies.

Revision ID: c3fc42fb9916
Revises: 05790c10b75b
Created: 2026-09-19 07:55:47.340409

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import greenlight_ai.db.types  # noqa: F401 - referenced by name in the column definitions
from sqlalchemy.dialects import postgresql
from sqlalchemy import Text

revision: str = "c3fc42fb9916"
down_revision: Union[str, None] = "05790c10b75b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "config_notes_snapshot",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
                nullable=False,
                server_default="[]",
            )
        )

    with op.batch_alter_table("training_observations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("configuration_id", sa.String(length=200), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column(
                "revisions",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.create_index(
            batch_op.f("ix_training_observations_configuration_id"),
            ["configuration_id"],
            unique=False,
        )


def downgrade() -> None:
    """Revert the change."""
    with op.batch_alter_table("training_observations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_training_observations_configuration_id"))
        batch_op.drop_column("revisions")
        batch_op.drop_column("is_active")
        batch_op.drop_column("configuration_id")

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("config_notes_snapshot")
