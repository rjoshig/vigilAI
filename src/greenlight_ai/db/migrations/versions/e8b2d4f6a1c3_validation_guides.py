"""validation guides on artifact types

An artifact type carries an ordered guide: what a report cell means and where it
answers to in the OSL and the configuration (Phase 6.8b, ADR-029).

Revision ID: e8b2d4f6a1c3
Revises: d7a1c2e4f6b8
Created: 2026-09-19 19:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "e8b2d4f6a1c3"
down_revision: Union[str, None] = "d7a1c2e4f6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("artifact_types", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "guide_entries",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    """Undo the change."""
    with op.batch_alter_table("artifact_types", schema=None) as batch_op:
        batch_op.drop_column("guide_entries")
