"""a column added nullable leaves every existing row NULL

Five columns on ``runs`` were added by earlier migrations without a backfill:
``coverage``, ``report_coverage``, ``notices``, ``keyword_suggestions`` and
``error_detail``. Every one is declared non-optional on the model and carries a Python
``default`` — which is an *insert* default. It applies to rows the ORM creates and to
nothing that already existed, so on any database older than those migrations every row
holds NULL where the model promises a value.

**The suite could not have caught this.** Tests build a database per run with
``create_all``, which reads ``Mapped[str]`` and writes NOT NULL — so a test database
cannot hold the NULL that a migrated one is full of. The migrated schema and the model
had drifted apart, and the tests only ever saw one of them. ``error_detail`` then failed
validation on the way out and answered 500 on the review screen, the most-used screen in
the user app, while every test stayed green.

This backfills all five, then makes each NOT NULL with a server default so the two
schemas say the same thing again. It is idempotent, touches only rows that are NULL, and
is portable across SQLite and Postgres (ADR-017): values are bound through typed columns
rather than written as literals, so a JSON column is handled by the dialect rather than
by a string that happens to look like JSON.

Only ``error_detail`` was breaking. The other four were the same defect waiting for the
first piece of code to read one without a ``or []`` beside it.

Revision ID: b8d0f2a4c6e9
Revises: a7c9e1b3d5f7
Created: 2026-09-21 01:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d0f2a4c6e9"
down_revision: Union[str, None] = "a7c9e1b3d5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Named rather than reflected, so the migration does not change meaning if the model
#: does. A migration describes one moment in the schema's history.
_RUNS = sa.table(
    "runs",
    sa.column("error_detail", sa.Text),
    sa.column("keyword_suggestions", sa.JSON),
    sa.column("coverage", sa.JSON),
    sa.column("report_coverage", sa.JSON),
    sa.column("notices", sa.JSON),
)

#: Each column, the empty value its model default would have given it, and the literal
#: a database writes for new rows. Three lists and two that are not.
_EMPTY: tuple[tuple[str, object, str], ...] = (
    ("error_detail", "", ""),
    ("keyword_suggestions", {}, "{}"),
    ("coverage", [], "[]"),
    ("report_coverage", [], "[]"),
    ("notices", [], "[]"),
)


def upgrade() -> None:
    """Backfill every affected column, then make the schema say what the model says."""
    for name, empty, _ in _EMPTY:
        column = _RUNS.c[name]
        op.execute(_RUNS.update().where(column.is_(None)).values({name: empty}))

    # SQLite cannot alter a column in place, so alembic rebuilds the table; Postgres
    # takes the ALTER directly. Both end at the schema `create_all` would have built.
    with op.batch_alter_table("runs") as batch:
        for name, _, literal in _EMPTY:
            batch.alter_column(
                name,
                existing_type=sa.Text() if name == "error_detail" else sa.JSON(),
                nullable=False,
                server_default=literal,
            )


def downgrade() -> None:
    """Loosen the columns again.

    The backfill is not undone: putting NULLs back would restore the defect, and there
    is no way to tell a row that was backfilled from one that was written empty.
    """
    with op.batch_alter_table("runs") as batch:
        for name, _, _ in _EMPTY:
            batch.alter_column(
                name,
                existing_type=sa.Text() if name == "error_detail" else sa.JSON(),
                nullable=True,
                server_default=None,
            )
