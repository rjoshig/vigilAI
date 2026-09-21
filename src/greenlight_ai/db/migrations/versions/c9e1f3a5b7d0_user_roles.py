"""an account holds several roles

One role per account made the reviewer impossible to express: a senior associate is a
reviewer *and* a user, and an administrator is nearly always a user too (ADR-049).

``roles`` is added NOT NULL with a server default so a migrated schema matches what
``create_all`` builds from the model — the divergence `b8d0f2a4c6e9` had to repair, and
which `tests/db/test_migration_chain.py` now asserts against.

``role`` stays, holding the strongest role in the list, so code that still asks
``role == "admin"`` keeps giving the right answer while the callers are moved over
(phase 6.20f removes it).

**The placeholder becomes a user and an administrator.** It is the account everything is
attributed to while login is off (ADR-022), and while login is off it can already do
everything — ``deps.py`` hands it ``is_admin=True``. This makes the stored roles say what
the behaviour already is, so that when the console starts gating on them the account
nobody can sign in as does not quietly lose the console.

Revision ID: c9e1f3a5b7d0
Revises: b8d0f2a4c6e9
Created: 2026-09-21 02:10:00.000000
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e1f3a5b7d0"
down_revision: Union[str, None] = "b8d0f2a4c6e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_USERS = sa.table(
    "users",
    sa.column("roles", sa.JSON),
    sa.column("role", sa.String),
    sa.column("is_placeholder", sa.Boolean),
)


def upgrade() -> None:
    """Give every account a list, and the placeholder both roles."""
    op.add_column(
        "users",
        sa.Column("roles", sa.JSON(), nullable=False, server_default=json.dumps(["user"])),
    )

    # Every existing account keeps exactly what it had, as a list of one.
    for name in ("user", "reviewer", "admin"):
        op.execute(_USERS.update().where(_USERS.c.role == name).values(roles=[name]))

    # The placeholder is both, because while login is off it already behaves as both.
    op.execute(
        _USERS.update()
        .where(_USERS.c.is_placeholder.is_(True))
        .values(roles=["user", "admin"], role="admin")
    )


def downgrade() -> None:
    """Drop the list. ``role`` was kept in step, so nothing is lost by doing so."""
    op.drop_column("users", "roles")
