"""a message an administrator schedules at the top of an app

"Maintenance starts at 11pm on the 6th." The tool cannot know it, nobody should
deploy to say it, and an email is read by whoever happens to open it (Phase 6.14g).

Revision ID: c3d5e7f9a1b4
Revises: b2c4d6e8f0a3
Created: 2026-09-21 09:00:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d5e7f9a1b4"
down_revision: Union[str, None] = "b2c4d6e8f0a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("audience", sa.String(length=20), nullable=False, server_default="both"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_announcements_level", "announcements", ["level"])
    op.create_index("ix_announcements_audience", "announcements", ["audience"])
    op.create_index("ix_announcements_is_active", "announcements", ["is_active"])


def downgrade() -> None:
    """Undo the change."""
    op.drop_index("ix_announcements_is_active", table_name="announcements")
    op.drop_index("ix_announcements_audience", table_name="announcements")
    op.drop_index("ix_announcements_level", table_name="announcements")
    op.drop_table("announcements")
