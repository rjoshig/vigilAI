"""compliance rules are versioned on edit

An edited compliance rule bumps its version, like a check, so a finding can say
which wording produced it (ADR-032).

Revision ID: f1c3e5a7b9d2
Revises: e8b2d4f6a1c3
Created: 2026-09-19 22:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1c3e5a7b9d2"
down_revision: Union[str, None] = "e8b2d4f6a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("compliance_rules", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    """Undo the change."""
    with op.batch_alter_table("compliance_rules", schema=None) as batch_op:
        batch_op.drop_column("version")
