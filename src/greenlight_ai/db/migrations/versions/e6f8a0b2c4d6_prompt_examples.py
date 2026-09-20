"""the administrator's library of worked examples

Every prompt's worked examples lived in Python, so an administrator could teach the
model background prose but not one "this wording means this requirement" pair
(Phase 6.13d, ADR-038). This is where theirs are kept.

Revision ID: e6f8a0b2c4d6
Revises: d5e7f9a1b3c5
Created: 2026-09-20 21:30:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f8a0b2c4d6"
down_revision: Union[str, None] = "d5e7f9a1b3c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "prompt_examples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False, server_default="everywhere"),
        sa.Column("given", sa.JSON(), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("origin", sa.String(length=60), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prompt_examples_stage", "prompt_examples", ["stage"])
    op.create_index("ix_prompt_examples_scope", "prompt_examples", ["scope"])
    op.create_index("ix_prompt_examples_origin", "prompt_examples", ["origin"])
    op.create_index("ix_prompt_examples_is_active", "prompt_examples", ["is_active"])


def downgrade() -> None:
    """Undo the change."""
    op.drop_index("ix_prompt_examples_is_active", table_name="prompt_examples")
    op.drop_index("ix_prompt_examples_origin", table_name="prompt_examples")
    op.drop_index("ix_prompt_examples_scope", table_name="prompt_examples")
    op.drop_index("ix_prompt_examples_stage", table_name="prompt_examples")
    op.drop_table("prompt_examples")
