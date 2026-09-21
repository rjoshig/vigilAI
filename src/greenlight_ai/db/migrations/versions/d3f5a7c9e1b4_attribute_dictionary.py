"""the attribute dictionary, and what a run spent reaching for it

Phase 6.22d. The ladder's fourth rung has existed since 6.21a with nothing to read.
It takes "other names that also mean this one", and the only caller that ever filled
it was the layout map — a handful of sheet and column names in a JSON column. An
attribute dictionary is a different shape: thousands of terms, a spelling per artifact,
provenance on each spelling. So it is tables (ADR-062).

Revision ID: d3f5a7c9e1b4
Revises: c2e4a6b8d0f3
Created: 2026-09-21 18:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f5a7c9e1b4"
down_revision: Union[str, None] = "c2e4a6b8d0f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change.

    The ``runs`` column is added nullable, backfilled, then made NOT NULL — the only
    order that works on a table with rows, and the shape
    ``tests/db/test_migration_chain.py`` exists to enforce.
    """
    op.create_table(
        "attribute_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.String(length=200), nullable=False, server_default="everywhere"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("canonical", "scope", name="uq_attribute_term_scope"),
    )
    op.create_index("ix_attribute_terms_canonical", "attribute_terms", ["canonical"])
    op.create_index("ix_attribute_terms_scope", "attribute_terms", ["scope"])
    op.create_index("ix_attribute_terms_is_active", "attribute_terms", ["is_active"])

    op.create_table(
        "attribute_spellings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "term_id",
            sa.Integer(),
            sa.ForeignKey("attribute_terms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("spelling", sa.String(length=200), nullable=False),
        sa.Column("artifact", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("origin", sa.String(length=30), nullable=False, server_default="admin"),
        sa.Column("origin_run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.UniqueConstraint("term_id", "spelling", "artifact", name="uq_attribute_spelling"),
    )
    op.create_index("ix_attribute_spellings_term_id", "attribute_spellings", ["term_id"])
    op.create_index("ix_attribute_spellings_spelling", "attribute_spellings", ["spelling"])
    op.create_index("ix_attribute_spellings_artifact", "attribute_spellings", ["artifact"])
    op.create_index("ix_attribute_spellings_origin", "attribute_spellings", ["origin"])
    op.create_index(
        "ix_attribute_spellings_origin_run_id", "attribute_spellings", ["origin_run_id"]
    )

    op.add_column("runs", sa.Column("attribute_locate_calls", sa.Integer(), nullable=True))
    op.execute("UPDATE runs SET attribute_locate_calls = 0 WHERE attribute_locate_calls IS NULL")
    with op.batch_alter_table("runs") as batch:
        batch.alter_column("attribute_locate_calls", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("runs", "attribute_locate_calls")
    op.drop_index("ix_attribute_spellings_origin_run_id", table_name="attribute_spellings")
    op.drop_index("ix_attribute_spellings_origin", table_name="attribute_spellings")
    op.drop_index("ix_attribute_spellings_artifact", table_name="attribute_spellings")
    op.drop_index("ix_attribute_spellings_spelling", table_name="attribute_spellings")
    op.drop_index("ix_attribute_spellings_term_id", table_name="attribute_spellings")
    op.drop_table("attribute_spellings")
    op.drop_index("ix_attribute_terms_is_active", table_name="attribute_terms")
    op.drop_index("ix_attribute_terms_scope", table_name="attribute_terms")
    op.drop_index("ix_attribute_terms_canonical", table_name="attribute_terms")
    op.drop_table("attribute_terms")
