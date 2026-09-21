"""what a delivery calls each sheet, and what shape it carried

Phase 6.21b and 6.21c. The fixed report checks named their sheets as Python constants, so
adapting to a customer's DIRT was an engineering deploy — the one thing this product
was designed to avoid. The names live on the artifact type now, and what the ladder's
fifth rung had to reason about is kept on the run so an administrator can accept it
(ADR-051).

Revision ID: a3c5e7f9b1d4
Revises: d2f4a6b8c0e1
Created: 2026-09-21 12:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3c5e7f9b1d4"
down_revision: Union[str, None] = "d2f4a6b8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change.

    Added nullable, backfilled, then made NOT NULL — which is the only order that
    works on a table with rows, and is the shape ``tests/db/test_migration_chain.py``
    exists to enforce. A column the migrations leave nullable while the model declares
    it NOT NULL means a migrated database holds NULLs a test database cannot, and the
    suite stays green while the product answers 500.
    """
    op.add_column("artifact_types", sa.Column("layout_entries", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("layout_suggestions", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("attribute_profile", sa.JSON(), nullable=True))
    op.execute("UPDATE artifact_types SET layout_entries = '[]' WHERE layout_entries IS NULL")
    op.execute("UPDATE runs SET layout_suggestions = '[]' WHERE layout_suggestions IS NULL")
    op.execute("UPDATE runs SET attribute_profile = '{}' WHERE attribute_profile IS NULL")
    with op.batch_alter_table("artifact_types") as batch:
        batch.alter_column("layout_entries", existing_type=sa.JSON(), nullable=False)
    with op.batch_alter_table("runs") as batch:
        batch.alter_column("layout_suggestions", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("attribute_profile", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("runs", "attribute_profile")
    op.drop_column("runs", "layout_suggestions")
    op.drop_column("artifact_types", "layout_entries")
