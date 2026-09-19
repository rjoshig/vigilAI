"""programme rules and keywords

A programme gains a keyword list for the classification check, with a server default
so existing rows satisfy it, and programme rules get their own table (ADR-026).

Revision ID: 64aeccf26047
Revises: c3fc42fb9916
Created: 2026-09-19 14:29:44.404059

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import greenlight_ai.db.types  # noqa: F401 - referenced by name in the column definitions
from sqlalchemy.dialects import postgresql
from sqlalchemy import Text

revision: str = "64aeccf26047"
down_revision: Union[str, None] = "c3fc42fb9916"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "programme_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope_code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("strictness", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(length=200), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", greenlight_ai.db.types.Utc(timezone=True), nullable=False),
        sa.Column("deleted_at", greenlight_ai.db.types.Utc(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("programme_rules", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_programme_rules_deleted_at"), ["deleted_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_programme_rules_scope_code"), ["scope_code"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_programme_rules_state"), ["state"], unique=False)

    with op.batch_alter_table("run_scopes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "keywords",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    """Revert the change."""
    with op.batch_alter_table("run_scopes", schema=None) as batch_op:
        batch_op.drop_column("keywords")

    with op.batch_alter_table("programme_rules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_programme_rules_state"))
        batch_op.drop_index(batch_op.f("ix_programme_rules_scope_code"))
        batch_op.drop_index(batch_op.f("ix_programme_rules_deleted_at"))

    op.drop_table("programme_rules")
