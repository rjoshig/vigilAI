"""the training loop and the rule lifecycle

Observations, candidate rules, field constraints, and the state machine every rule
moves through (ADR-021). Existing rules arrive as active and admin, which is
what they already were; nothing changes behaviour on upgrade.

Revision ID: 05790c10b75b
Revises: 23356f1b8aeb
Created: 2026-09-18 17:53:49.696385

Additive changes only, portable across SQLite and Postgres (ADR-017).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import vigilai.db.types  # noqa: F401 - referenced by name in the column definitions
from sqlalchemy.dialects import postgresql
from sqlalchemy import Text

revision: str = "05790c10b75b"
down_revision: Union[str, None] = "23356f1b8aeb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the change."""
    op.create_table(
        "field_constraints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("field", sa.String(length=200), nullable=False),
        sa.Column("constraint", sa.String(length=40), nullable=False),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "report_kinds",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="admin"),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.Column("deleted_at", vigilai.db.types.Utc(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("field_constraints", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_field_constraints_deleted_at"), ["deleted_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_field_constraints_field"), ["field"], unique=False)
        batch_op.create_index(batch_op.f("ix_field_constraints_state"), ["state"], unique=False)

    op.create_table(
        "rule_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_kind", sa.String(length=30), nullable=False),
        sa.Column(
            "body",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.String(length=200), nullable=False),
        sa.Column(
            "source_observation_ids",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=False),
        sa.Column(
            "model_draft",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("model_used", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column(
            "conflicts",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "replay",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.String(length=200), nullable=False),
        sa.Column("decided_at", vigilai.db.types.Utc(timezone=True), nullable=True),
        sa.Column("created_at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name="fk_created_by_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], name="fk_decided_by_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("rule_candidates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_rule_candidates_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_rule_candidates_status"), ["status"], unique=False)

    op.create_table(
        "rule_state_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_kind", sa.String(length=30), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(length=20), nullable=False),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_actor_user_id_users"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("rule_state_changes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_rule_state_changes_at"), ["at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_rule_state_changes_rule_id"), ["rule_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_rule_state_changes_rule_kind"), ["rule_kind"], unique=False
        )

    op.create_table(
        "training_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("finding_id", sa.Integer(), nullable=True),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "anchors",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("expectation", sa.Text(), nullable=False),
        sa.Column("severity_hint", sa.String(length=20), nullable=False),
        sa.Column("scope_hint", sa.String(length=30), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("scope_code", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_note", sa.Text(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("synthesized_at", vigilai.db.types.Utc(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.Column("updated_at", vigilai.db.types.Utc(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], name="fk_author_user_id_users"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("training_observations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_training_observations_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_training_observations_customer_name"), ["customer_name"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_training_observations_kind"), ["kind"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_training_observations_run_id"), ["run_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_training_observations_status"), ["status"], unique=False
        )

    with op.batch_alter_table("check_definitions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("state", sa.String(length=20), nullable=False, server_default="active")
        )
        batch_op.add_column(
            sa.Column("origin", sa.String(length=20), nullable=False, server_default="admin")
        )
        batch_op.add_column(sa.Column("candidate_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("deleted_at", vigilai.db.types.Utc(timezone=True), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_check_definitions_deleted_at"), ["deleted_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_check_definitions_state"), ["state"], unique=False)

    with op.batch_alter_table("compliance_rules", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("state", sa.String(length=20), nullable=False, server_default="active")
        )
        batch_op.add_column(
            sa.Column("origin", sa.String(length=20), nullable=False, server_default="admin")
        )
        batch_op.add_column(sa.Column("candidate_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("deleted_at", vigilai.db.types.Utc(timezone=True), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_compliance_rules_deleted_at"), ["deleted_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_compliance_rules_state"), ["state"], unique=False)

    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("shadow", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_index(batch_op.f("ix_findings_shadow"), ["shadow"], unique=False)


def downgrade() -> None:
    """Revert the change."""
    with op.batch_alter_table("findings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_findings_shadow"))
        batch_op.drop_column("shadow")

    with op.batch_alter_table("compliance_rules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_compliance_rules_state"))
        batch_op.drop_index(batch_op.f("ix_compliance_rules_deleted_at"))
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("candidate_id")
        batch_op.drop_column("origin")
        batch_op.drop_column("state")

    with op.batch_alter_table("check_definitions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_check_definitions_state"))
        batch_op.drop_index(batch_op.f("ix_check_definitions_deleted_at"))
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("candidate_id")
        batch_op.drop_column("origin")
        batch_op.drop_column("state")

    with op.batch_alter_table("training_observations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_training_observations_status"))
        batch_op.drop_index(batch_op.f("ix_training_observations_run_id"))
        batch_op.drop_index(batch_op.f("ix_training_observations_kind"))
        batch_op.drop_index(batch_op.f("ix_training_observations_customer_name"))
        batch_op.drop_index(batch_op.f("ix_training_observations_created_at"))

    op.drop_table("training_observations")
    with op.batch_alter_table("rule_state_changes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_rule_state_changes_rule_kind"))
        batch_op.drop_index(batch_op.f("ix_rule_state_changes_rule_id"))
        batch_op.drop_index(batch_op.f("ix_rule_state_changes_at"))

    op.drop_table("rule_state_changes")
    with op.batch_alter_table("rule_candidates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_rule_candidates_status"))
        batch_op.drop_index(batch_op.f("ix_rule_candidates_created_at"))

    op.drop_table("rule_candidates")
    with op.batch_alter_table("field_constraints", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_field_constraints_state"))
        batch_op.drop_index(batch_op.f("ix_field_constraints_field"))
        batch_op.drop_index(batch_op.f("ix_field_constraints_deleted_at"))

    op.drop_table("field_constraints")
