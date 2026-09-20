"""the artifacts disagreed with what the submitter typed

A run whose configuration id, customer or credit date disagrees with what the
artifacts declare is held until somebody accepts the disagreement with a reason
(Phase 6.14a, ADR-041). One row per field that did not agree; rows are never
deleted, so the review screen and the frozen report can both show what was waived.

Revision ID: a1b3c5d7e9f2
Revises: e6f8a0b2c4d6
Created: 2026-09-20 22:10:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b3c5d7e9f2"
down_revision: Union[str, None] = "e6f8a0b2c4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "artifact_mismatches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("submitted", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("declared", sa.String(length=400), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="different"),
        sa.Column("source", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("accepted_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "field", name="uq_artifact_mismatch_run_field"),
    )


def downgrade() -> None:
    """Undo the change."""
    op.drop_table("artifact_mismatches")
