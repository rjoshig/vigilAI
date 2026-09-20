"""words that would have matched, offered to an administrator

The model read a delivery as the programme its submitter declared, where the keyword
list did not (Phase 6.18f). The words it quoted are kept on the run so somebody can
close the gap; nothing applies them (ADR-045).

Revision ID: f2a4c6e8b1d3
Revises: e9f1a3c5b7d2
Created: 2026-09-20 16:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a4c6e8b1d3"
down_revision: Union[str, None] = "e9f1a3c5b7d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.add_column("runs", sa.Column("keyword_suggestions", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("runs", "keyword_suggestions")
