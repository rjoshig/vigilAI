"""several samples per artifact type

Revision ID: 03289b09c30b
Revises: 71906528d2aa
Created: 2026-09-18

An artifact type held one sample, in ``filename`` and ``storage_path``. It now holds
up to three in their own table (ADR-021), because real report layouts vary between
customers and one sample hides that.

The old columns are dropped, so the **data moves first**: any sample already uploaded
becomes the type's first row here. Dropping them without that would quietly lose every
named value's resolution target, which is the sort of migration that looks fine until
the next check is tested.
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import column, table

import vigilai.db.types  # noqa: F401 - referenced by name in the column definitions

revision: str = "03289b09c30b"
down_revision: Union[str, None] = "71906528d2aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "artifact_samples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_type_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("filename", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("storage_path", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sheets", _JSON, nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_type_id"],
            ["artifact_types.id"],
            name="fk_artifact_samples_artifact_type_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], name="fk_artifact_samples_uploaded_by_user_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("artifact_samples", schema=None) as batch_op:
        batch_op.create_index(
            "ix_artifact_samples_artifact_type_id", ["artifact_type_id"], unique=False
        )
        batch_op.create_index("ix_artifact_samples_sha256", ["sha256"], unique=False)

    # Move what is already there before the columns holding it disappear.
    types = table(
        "artifact_types",
        column("id", sa.Integer),
        column("filename", sa.String),
        column("storage_path", sa.String),
        column("notes", sa.Text),
    )
    bind = op.get_bind()
    existing = bind.execute(
        sa.select(types.c.id, types.c.filename, types.c.storage_path, types.c.notes).where(
            types.c.storage_path != ""
        )
    ).all()
    moved_at = dt.datetime.now(dt.timezone.utc)
    if existing:
        op.bulk_insert(
            table(
                "artifact_samples",
                column("artifact_type_id", sa.Integer),
                column("label", sa.String),
                column("filename", sa.String),
                column("storage_path", sa.String),
                column("sha256", sa.String),
                column("size_bytes", sa.BigInteger),
                column("sheets", _JSON),
                column("notes", sa.Text),
                column("uploaded_by", sa.String),
                column("created_at", vigilai.db.types.Utc(timezone=True)),
            ),
            [
                {
                    "artifact_type_id": row.id,
                    "label": "the original sample",
                    "filename": row.filename or "",
                    "storage_path": row.storage_path,
                    "sha256": "",
                    "size_bytes": 0,
                    # Left empty: the console reads the sheets from the file on the
                    # next upload, and guessing here would need to open every
                    # workbook during a migration.
                    "sheets": [],
                    "notes": row.notes or "",
                    "uploaded_by": "",
                    "created_at": moved_at,
                }
                for row in existing
            ],
        )

    with op.batch_alter_table("artifact_types", schema=None) as batch_op:
        batch_op.drop_column("storage_path")
        batch_op.drop_column("filename")


def downgrade() -> None:
    """Revert the change, keeping each type's first sample."""
    with op.batch_alter_table("artifact_types", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("filename", sa.VARCHAR(length=500), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("storage_path", sa.VARCHAR(length=500), nullable=False, server_default="")
        )

    bind = op.get_bind()
    samples = table(
        "artifact_samples",
        column("id", sa.Integer),
        column("artifact_type_id", sa.Integer),
        column("filename", sa.String),
        column("storage_path", sa.String),
    )
    types = table(
        "artifact_types",
        column("id", sa.Integer),
        column("filename", sa.String),
        column("storage_path", sa.String),
    )
    seen: set[int] = set()
    for row in bind.execute(
        sa.select(samples.c.artifact_type_id, samples.c.filename, samples.c.storage_path).order_by(
            samples.c.id
        )
    ).all():
        if row.artifact_type_id in seen:
            continue
        seen.add(row.artifact_type_id)
        bind.execute(
            sa.update(types)
            .where(types.c.id == row.artifact_type_id)
            .values(filename=row.filename, storage_path=row.storage_path)
        )

    with op.batch_alter_table("artifact_samples", schema=None) as batch_op:
        batch_op.drop_index("ix_artifact_samples_sha256")
        batch_op.drop_index("ix_artifact_samples_artifact_type_id")

    op.drop_table("artifact_samples")
