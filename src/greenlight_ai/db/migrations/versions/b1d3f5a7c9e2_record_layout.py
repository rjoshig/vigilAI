"""the delivered file's record schema, as a fourth artifact

Phase 6.22b. The tool reconciled three things and had no account of the delivered file
itself, so a DIRT column it could not resolve had nothing to be looked up in. A record
layout is one row per delivered field with its name, data type and size; it is
uploaded per run and remembered for the configuration, promoted by whichever run
finalizes.

Revision ID: b1d3f5a7c9e2
Revises: a3c5e7f9b1d4
Created: 2026-09-21 14:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1d3f5a7c9e2"
down_revision: Union[str, None] = "a3c5e7f9b1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change.

    The two ``runs`` columns are added nullable, backfilled, then made NOT NULL. That
    order is the only one that works on a table with rows, and leaving either step out
    is the defect ``tests/db/test_migration_chain.py`` exists to catch: a migrated
    database full of NULLs the model says cannot exist, and a suite that stays green
    because it builds its schema with ``create_all``.
    """
    op.create_table(
        "record_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("configuration_id", sa.String(length=200), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("source_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_filename", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promoted_by", sa.String(length=200), nullable=False, server_default=""),
        sa.UniqueConstraint("customer_name", "configuration_id", name="uq_record_layout_config"),
    )
    op.create_index("ix_record_layouts_customer_name", "record_layouts", ["customer_name"])
    op.create_index("ix_record_layouts_configuration_id", "record_layouts", ["configuration_id"])
    op.create_index("ix_record_layouts_source_run_id", "record_layouts", ["source_run_id"])

    op.add_column("runs", sa.Column("record_layout", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("record_layout_run_id", sa.Integer(), nullable=True))
    op.add_column(
        "runs", sa.Column("record_layout_source_date", sa.String(length=10), nullable=True)
    )
    op.execute("UPDATE runs SET record_layout = '[]' WHERE record_layout IS NULL")
    op.execute("UPDATE runs SET record_layout_run_id = 0 WHERE record_layout_run_id IS NULL")
    op.execute(
        "UPDATE runs SET record_layout_source_date = '' WHERE record_layout_source_date IS NULL"
    )
    with op.batch_alter_table("runs") as batch:
        batch.alter_column("record_layout", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("record_layout_run_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column(
            "record_layout_source_date", existing_type=sa.String(length=10), nullable=False
        )


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("runs", "record_layout_source_date")
    op.drop_column("runs", "record_layout_run_id")
    op.drop_column("runs", "record_layout")
    op.drop_index("ix_record_layouts_source_run_id", table_name="record_layouts")
    op.drop_index("ix_record_layouts_configuration_id", table_name="record_layouts")
    op.drop_index("ix_record_layouts_customer_name", table_name="record_layouts")
    op.drop_table("record_layouts")
