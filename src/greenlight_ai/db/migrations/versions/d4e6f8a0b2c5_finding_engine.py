"""which path produced a finding: code, or the model reading first

Stage 6 is the first place both happen (Phase 6.15), so a run can no longer be
described by its token count alone (Phase 6.16).

Revision ID: d4e6f8a0b2c5
Revises: c3d5e7f9a1b4
Created: 2026-09-21 14:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e6f8a0b2c5"
down_revision: Union[str, None] = "c3d5e7f9a1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.add_column(
        "findings",
        sa.Column("engine", sa.String(length=10), nullable=False, server_default="code"),
    )
    op.create_index("ix_findings_engine", "findings", ["engine"])


def downgrade() -> None:
    """Undo the change."""
    op.drop_index("ix_findings_engine", table_name="findings")
    op.drop_column("findings", "engine")
