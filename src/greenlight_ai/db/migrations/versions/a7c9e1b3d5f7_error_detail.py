"""the failure at length, for somebody tracing it

The runs list shows a line and the run itself showed the same line. Neither was
enough to act on: a failure at stage 4 says "PipelineError: s4_trace: …" and nothing
about where in the code it came from (Phase 6.19).

Revision ID: a7c9e1b3d5f7
Revises: f2a4c6e8b1d3
Created: 2026-09-20 19:10:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1b3d5f7"
down_revision: Union[str, None] = "f2a4c6e8b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.add_column("runs", sa.Column("error_detail", sa.Text(), nullable=True))


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("runs", "error_detail")
