"""product codes, and the expansion a run was checked against

Phase 6.22c. An OSL says either "deliver AT01, AT02, ST" or "deliver all attributes
from ABC", and both have to reach the same check. A product code names a set of
attributes; expanding one is code and never the model (ADR-061), and this table is
what decides whether a code the model read names anything at all.

Revision ID: c2e4a6b8d0f3
Revises: b1d3f5a7c9e2
Created: 2026-09-21 16:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2e4a6b8d0f3"
down_revision: Union[str, None] = "b1d3f5a7c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change.

    The ``runs`` column is added nullable, backfilled, then made NOT NULL — the only
    order that works on a table with rows, and the shape
    ``tests/db/test_migration_chain.py`` exists to enforce.
    """
    op.create_table(
        "product_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.String(length=200), nullable=False, server_default="everywhere"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("code", "scope", name="uq_product_code_scope"),
    )
    op.create_index("ix_product_codes_code", "product_codes", ["code"])
    op.create_index("ix_product_codes_scope", "product_codes", ["scope"])
    op.create_index("ix_product_codes_is_active", "product_codes", ["is_active"])

    op.create_table(
        "product_code_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_code_id",
            sa.Integer(),
            sa.ForeignKey("product_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attribute_name", sa.String(length=200), nullable=False),
        sa.Column("output_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.UniqueConstraint("product_code_id", "attribute_name", name="uq_product_member"),
    )
    op.create_index(
        "ix_product_code_members_product_code_id", "product_code_members", ["product_code_id"]
    )
    op.create_index(
        "ix_product_code_members_attribute_name", "product_code_members", ["attribute_name"]
    )

    op.add_column("runs", sa.Column("product_code_attributes", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE runs SET product_code_attributes = '{}' WHERE product_code_attributes IS NULL"
    )
    with op.batch_alter_table("runs") as batch:
        batch.alter_column("product_code_attributes", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    """Undo the change."""
    op.drop_column("runs", "product_code_attributes")
    op.drop_index("ix_product_code_members_attribute_name", table_name="product_code_members")
    op.drop_index("ix_product_code_members_product_code_id", table_name="product_code_members")
    op.drop_table("product_code_members")
    op.drop_index("ix_product_codes_is_active", table_name="product_codes")
    op.drop_index("ix_product_codes_scope", table_name="product_codes")
    op.drop_index("ix_product_codes_code", table_name="product_codes")
    op.drop_table("product_codes")
