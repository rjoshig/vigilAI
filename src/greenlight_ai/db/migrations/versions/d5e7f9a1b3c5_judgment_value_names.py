"""the named values a judgment check may show the model

A judgment check was definable and never ran (Phase 6.13c, D9). To run it under
ADR-001 the model must see only the values the administrator listed, so a check
names them.

Revision ID: d5e7f9a1b3c5
Revises: c4e6a8b0d2f4
Created: 2026-09-20 20:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e7f9a1b3c5"
down_revision: Union[str, None] = "c4e6a8b0d2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("check_definitions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("value_names", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Undo the change."""
    with op.batch_alter_table("check_definitions", schema=None) as batch_op:
        batch_op.drop_column("value_names")
