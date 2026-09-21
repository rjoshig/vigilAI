"""an observation may be a mapping: what this delivery calls one attribute

Phase 6.22f. Any user may propose one while Train AI mode is on; a reviewer or an
administrator approves it, in the existing queue, and approving writes the dictionary
spelling. The two names live in a column of their own rather than folded into an
anchor, because they are the substance of the observation and not a pointer to where
it was seen.

Revision ID: f5b7d9c1e3a6
Revises: e4a6c8b0d2f5
Created: 2026-09-21 21:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5b7d9c1e3a6"
down_revision: Union[str, None] = "e4a6c8b0d2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change.

    Added nullable, backfilled, then made NOT NULL — the only order that works on a
    table with rows, and the shape ``tests/db/test_migration_chain.py`` enforces.
    """
    op.add_column("training_observations", sa.Column("mapping", sa.JSON(), nullable=True))
    op.execute("UPDATE training_observations SET mapping = '{}' WHERE mapping IS NULL")
    with op.batch_alter_table("training_observations") as batch:
        batch.alter_column("mapping", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("training_observations", "mapping")
