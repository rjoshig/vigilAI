"""drop the single role column

Nothing reads it any more. ``roles`` has held the whole set since `c9e1f3a5b7d0`, every
router asks about capabilities rather than about a role name (ADR-049), and the two
places that counted administrators in SQL now count them in Python over the list — so
the column was a second answer to a question with one answer, and a second answer is
where the two get to disagree.

Dropped inside ``batch_alter_table``, which is how a column is removed portably: older
SQLite has no ``ALTER TABLE ... DROP COLUMN`` and alembic rebuilds the table instead,
while Postgres takes the plain statement.

The downgrade puts the column back and refills it from the list, so a rollback lands on
a schema the previous revision can work with rather than on one full of nulls.

Revision ID: d2f4a6b8c0e1
Revises: c9e1f3a5b7d0
Created: 2026-09-21 04:15:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4a6b8c0e1"
down_revision: Union[str, None] = "c9e1f3a5b7d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Weakest first, which is the order the list is stored in, so the last one present is
#: the strongest held — what the column used to mean.
_ROLES: tuple[str, ...] = ("user", "reviewer", "admin")


def upgrade() -> None:
    """Remove the column the role list replaced."""
    with op.batch_alter_table("users") as batch:
        batch.drop_column("role")


def downgrade() -> None:
    """Put it back, carrying the strongest role each account holds."""
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role", sa.String(50), nullable=False, server_default="user"))

    users = sa.table("users", sa.column("roles", sa.JSON), sa.column("role", sa.String))
    # Weakest first, so a stronger role overwrites a weaker one and the last write wins.
    # Matched as text rather than with a JSON operator, because those are spelled
    # differently on SQLite and Postgres and this has to run on both (ADR-017).
    for name in _ROLES:
        op.execute(
            users.update()
            .where(sa.cast(users.c.roles, sa.Text).like(f'%"{name}"%'))
            .values(role=name)
        )
