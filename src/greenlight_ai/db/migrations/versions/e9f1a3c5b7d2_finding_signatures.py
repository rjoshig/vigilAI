"""what a reviewer has stopped needing to see

The verdicts people give have been counted since Phase 6.13 and read by nothing. This
is the table that reads them (Phase 6.18a). It records what demotion *would* do; in
6.18a nothing acts on it.

Revision ID: e9f1a3c5b7d2
Revises: d4e6f8a0b2c5
Created: 2026-09-20 12:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f1a3c5b7d2"
down_revision: Union[str, None] = "d4e6f8a0b2c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "finding_signatures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signature", sa.String(length=40), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("rule_ref", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("finding_type", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("element_ref", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="watching"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dismissed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upheld", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severities", sa.JSON(), nullable=False),
        sa.Column("justified_by_run_ids", sa.JSON(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_finding_signatures_signature", "finding_signatures", ["signature"], unique=True
    )
    op.create_index("ix_finding_signatures_customer", "finding_signatures", ["customer_name"])
    op.create_index("ix_finding_signatures_scope", "finding_signatures", ["scope"])
    op.create_index("ix_finding_signatures_state", "finding_signatures", ["state"])
    op.create_index("ix_finding_signatures_last_seen", "finding_signatures", ["last_seen"])


def downgrade() -> None:
    """Undo the change."""
    op.drop_index("ix_finding_signatures_last_seen", table_name="finding_signatures")
    op.drop_index("ix_finding_signatures_state", table_name="finding_signatures")
    op.drop_index("ix_finding_signatures_scope", table_name="finding_signatures")
    op.drop_index("ix_finding_signatures_customer", table_name="finding_signatures")
    op.drop_index("ix_finding_signatures_signature", table_name="finding_signatures")
    op.drop_table("finding_signatures")
