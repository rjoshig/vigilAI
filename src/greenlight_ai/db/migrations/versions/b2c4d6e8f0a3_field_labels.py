"""what a delivery calls the fields the tool checks

The credit date is written "as-of date", "data date", "cycle date" or "extract
date" depending on who built the report, and a check that greps for the date's
value can report absence but never a mismatch (Phase 6.14b, ADR-041).

Revision ID: b2c4d6e8f0a3
Revises: a1b3c5d7e9f2
Created: 2026-09-20 23:05:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c4d6e8f0a3"
down_revision: Union[str, None] = "a1b3c5d7e9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "field_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical", sa.String(length=40), nullable=False, index=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False, server_default="everywhere"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical", "label", "scope", name="uq_field_label"),
    )
    op.create_index("ix_field_labels_scope", "field_labels", ["scope"])
    op.create_index("ix_field_labels_is_active", "field_labels", ["is_active"])


def downgrade() -> None:
    """Undo the change."""
    op.drop_index("ix_field_labels_is_active", table_name="field_labels")
    op.drop_index("ix_field_labels_scope", table_name="field_labels")
    op.drop_table("field_labels")
