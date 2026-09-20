"""scoped samples and meaning entries

A sample belongs to a delivery programme or is global; a meaning entry maps an OSL
requirement to the config block that implements it and the report cells that
evidence it (Phase 6.10, ADR-033).

Revision ID: a4b6c8d0e2f4
Revises: f1c3e5a7b9d2
Created: 2026-09-20 03:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

import greenlight_ai.db.types  # noqa: F401 - referenced by name in the column definitions

revision: str = "a4b6c8d0e2f4"
down_revision: Union[str, None] = "f1c3e5a7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    """Apply the change."""
    with op.batch_alter_table("artifact_samples", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("scope_code", sa.String(length=20), nullable=False, server_default="")
        )
        batch_op.create_index(
            batch_op.f("ix_artifact_samples_scope_code"), ["scope_code"], unique=False
        )

    op.create_table(
        "meaning_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope_code", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("osl_section", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("osl_phrase", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("requirement_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("config_path", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("report_cells", _JSON, nullable=False, server_default="[]"),
        sa.Column("meaning", sa.Text(), nullable=False, server_default=""),
        sa.Column("validate", sa.Text(), nullable=False, server_default=""),
        sa.Column("comparison", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("tolerance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("examples", _JSON, nullable=False, server_default="[]"),
        sa.Column("compliance_suggestion", _JSON, nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("proposed_by", sa.String(length=20), nullable=False, server_default="model"),
        sa.Column("confirmed_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("confirmed_at", greenlight_ai.db.types.Utc(timezone=True), nullable=True),
        sa.Column("created_at", greenlight_ai.db.types.Utc(timezone=True), nullable=False),
        sa.Column("updated_at", greenlight_ai.db.types.Utc(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_code", "key", name="uq_meaning_entry"),
    )
    with op.batch_alter_table("meaning_entries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_meaning_entries_scope_code"), ["scope_code"])
        batch_op.create_index(batch_op.f("ix_meaning_entries_status"), ["status"])


def downgrade() -> None:
    """Undo the change."""
    with op.batch_alter_table("meaning_entries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_meaning_entries_status"))
        batch_op.drop_index(batch_op.f("ix_meaning_entries_scope_code"))
    op.drop_table("meaning_entries")
    with op.batch_alter_table("artifact_samples", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artifact_samples_scope_code"))
        batch_op.drop_column("scope_code")
