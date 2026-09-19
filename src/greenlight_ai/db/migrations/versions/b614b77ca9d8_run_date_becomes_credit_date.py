"""run date becomes credit date

The date a run carried was never the day it ran; it was the credit date the delivery
is cut as of, which the reports state and the tool now checks (ADR-027).

Revision ID: b614b77ca9d8
Revises: c3fc42fb9916
Created: 2026-09-19 14:55:15.079404

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b614b77ca9d8"
down_revision: Union[str, None] = "64aeccf26047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename the column; the values are the same dates under a truer name."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column("run_date", new_column_name="credit_date")


def downgrade() -> None:
    """Put the old name back."""
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column("credit_date", new_column_name="run_date")
