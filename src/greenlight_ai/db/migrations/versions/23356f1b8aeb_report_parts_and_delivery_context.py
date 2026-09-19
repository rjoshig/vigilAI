"""report parts and delivery context

A report kind can arrive as several files, each with a label (ADR-021), and a run can
state how many deliverables the campaign has so code can check the two against each
other. Every new column carries a server default so an existing row satisfies it.

Revision ID: 23356f1b8aeb
Revises: 03289b09c30b
Created: 2026-09-18 17:39:28.460652

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import greenlight_ai.db.types  # noqa: F401 - referenced by name in the column definitions

revision: str = "23356f1b8aeb"
down_revision: Union[str, None] = "03289b09c30b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("run_files", schema=None) as batch_op:
        batch_op.add_column(sa.Column("part", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(
            sa.Column("part_label", sa.String(length=200), nullable=False, server_default="")
        )

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("deliverable_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("outputs_validated", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("delivery_notes", sa.Text(), nullable=False, server_default="")
        )


def downgrade() -> None:
    """Revert the change."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("delivery_notes")
        batch_op.drop_column("outputs_validated")
        batch_op.drop_column("deliverable_count")

    with op.batch_alter_table("run_files", schema=None) as batch_op:
        batch_op.drop_column("part_label")
        batch_op.drop_column("part")
