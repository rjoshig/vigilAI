"""coverage per run, acknowledgements, and the finalize attestation

A run records what it checked and what it did not (Phase 6.11c), a person
acknowledges each requirement no report evidenced (6.11d), and the frozen
report carries the attestation they confirmed.

Revision ID: b2d4f6a8c1e3
Revises: a4b6c8d0e2f4
Created: 2026-09-20 12:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a8c1e3"
down_revision: Union[str, None] = "a4b6c8d0e2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("coverage", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("report_coverage", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("notices", sa.JSON(), nullable=True))

    op.create_table(
        "coverage_acknowledgements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # The requirement's id within the run, or a finding id for a check that could
        # not be evaluated. One column for both because the gate asks the same
        # question of each: has a person seen that this was not checked?
        sa.Column("target", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="requirement"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor", sa.String(200), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "target", name="uq_coverage_ack_run_target"),
    )

    with op.batch_alter_table("final_reports", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attestation", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Undo the change."""
    with op.batch_alter_table("final_reports", schema=None) as batch_op:
        batch_op.drop_column("attestation")
    op.drop_table("coverage_acknowledgements")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("notices")
        batch_op.drop_column("report_coverage")
        batch_op.drop_column("coverage")
