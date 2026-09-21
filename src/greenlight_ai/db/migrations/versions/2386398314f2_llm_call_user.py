"""a model call records who asked for it, when a person did

Phase 8f. Every pipeline call belongs to a run, and the run says whose it was. The
report chat is the first call in the product a person makes directly: there is a run,
but the person asking about it is very often not the person who submitted it, so
attributing a question to the run's submitter would put somebody else's usage on their
name and make the per-person daily cap meaningless.

Nullable, and null for every pipeline call. A column that said "the pipeline" would be
a second way of expressing what ``run_id`` already says, and the first place the two
could disagree.

Revision ID: 2386398314f2
Revises: f5b7d9c1e3a6
Created: 2026-09-21 23:30:00.000000

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2386398314f2"
down_revision: Union[str, None] = "f5b7d9c1e3a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change.

    No foreign key: `llm_calls` rows deliberately outlive the runs they belong to so
    aggregated usage survives a retention purge, and a constraint pointing at `users`
    would make deleting an account either impossible or silently destructive of the
    numbers. The id is kept as a plain integer and read defensively, exactly as
    ``run_id`` already is once its run is gone.
    """
    op.add_column("llm_calls", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_llm_calls_user_id", "llm_calls", ["user_id"])


def downgrade() -> None:
    """Undo the change."""
    op.drop_index("ix_llm_calls_user_id", table_name="llm_calls")
    op.drop_column("llm_calls", "user_id")
