"""an optional second approver per delivery programme

A programme can require that someone other than the reviewer signs off a run
whose serious findings the reviewer waved through (ADR-036). Off by default.

Revision ID: c4e6a8b0d2f4
Revises: b2d4f6a8c1e3
Created: 2026-09-20 18:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e6a8b0d2f4"
down_revision: Union[str, None] = "b2d4f6a8c1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("run_scopes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("second_approver", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    op.create_table(
        "second_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("actor", sa.String(200), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("covered", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", name="uq_second_approval_run"),
    )


def downgrade() -> None:
    """Undo the change."""
    op.drop_table("second_approvals")
    with op.batch_alter_table("run_scopes", schema=None) as batch_op:
        batch_op.drop_column("second_approver")
