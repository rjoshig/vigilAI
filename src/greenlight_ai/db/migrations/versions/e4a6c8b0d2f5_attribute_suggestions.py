"""what the delivery appears to call each attribute the tool could not locate

Phase 6.22f. The record layout proposes the mapping in code where it settles the
question, and the ladder's fifth rung where it does not. A suggestion is a suggestion
until somebody accepts it into the dictionary (ADR-021).

Revision ID: e4a6c8b0d2f5
Revises: d3f5a7c9e1b4
Created: 2026-09-21 20:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4a6c8b0d2f5"
down_revision: Union[str, None] = "d3f5a7c9e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change.

    Added nullable, backfilled, then made NOT NULL — the only order that works on a
    table with rows, and the shape ``tests/db/test_migration_chain.py`` enforces.
    """
    op.add_column("runs", sa.Column("attribute_suggestions", sa.JSON(), nullable=True))
    op.execute("UPDATE runs SET attribute_suggestions = '[]' WHERE attribute_suggestions IS NULL")
    with op.batch_alter_table("runs") as batch:
        batch.alter_column("attribute_suggestions", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("runs", "attribute_suggestions")
