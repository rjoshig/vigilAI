"""SQLAlchemy models: every table in ``docs/design.md`` "Data model".

Portable across SQLite and Postgres (ADR-017): JSON columns use the variant in
:mod:`vigilai.db.types`, timestamps come back timezone-aware on both, and no
Postgres-only DDL appears here.

The ``users`` table is created and left empty. v1 has no login, but the provision stays
so login can be added to the admin-ui first without a migration that rewrites
foreign keys (ADR-008).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from vigilai.db.types import Json, Utc, utcnow

__all__ = [
    "Base",
    "User",
    "Run",
    "RunFile",
    "Config",
    "Rule",
    "ConfigElement",
    "Trace",
    "Finding",
    "RunStage",
    "LlmCall",
    "LlmCacheEntry",
    "AttributeAlias",
    "MaskedColumn",
    "AuditLog",
    "ArtifactType",
    "RunScope",
    "NamedValueRow",
    "CheckDefinitionRow",
    "ComplianceRuleRow",
    "ReversePassCategoryRow",
    "FinalReport",
    "Job",
    "RETENTION_DAYS",
]

#: Runs expire this long after creation; the purge job deletes by ``runs.expires_at``
#: and cascades to the files on the shared volume (``docs/design.md`` "Data model").
RETENTION_DAYS: int = 90


class Base(DeclarativeBase):
    """Declarative base for every table."""


def _pk() -> Mapped[int]:
    """Build the standard surrogate primary key.

    Returns:
        An autoincrementing integer primary key. Integers rather than UUIDs because both
        backends generate them without an extension and the ids are never public.
    """
    return mapped_column(sa.Integer, primary_key=True, autoincrement=True)


class User(Base):
    """An account. Present whether or not login is enabled (ADR-022).

    One row always exists: the placeholder every action is attributed to while login
    is off. Accounts are created by an administrator and **deactivated, never
    deleted**, so what a person did stays attributed to them.
    """

    __tablename__ = "users"

    id: Mapped[int] = _pk()
    #: What is typed at the sign-in prompt, e.g. ``admin``.
    username: Mapped[str] = mapped_column(sa.String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(200), default="")
    email: Mapped[str] = mapped_column(sa.String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(200), default="")
    #: ``admin`` or ``user``. Two roles, no permission matrix.
    role: Mapped[str] = mapped_column(sa.String(50), default="user")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    #: Set on every account an administrator creates, including the bootstrap admin:
    #: a password another person typed is already known to two people.
    must_change_password: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    #: The account attributed to while login is off. Cannot sign in, cannot be deleted.
    is_placeholder: Mapped[bool] = mapped_column(sa.Boolean, default=False, index=True)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    locked_until: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    deactivated_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class UserSession(Base):
    """One signed-in session.

    Server-side rather than a self-contained token, because revoking a session and
    knowing who is signed in both matter more here than saving a database read. Only a
    hash of the token is stored, so the table is not a set of working credentials.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = _pk()
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: How the session was established. ``password`` today; the column exists so an
    #: external identity provider can attach here later without a migration (ADR-022).
    origin: Mapped[str] = mapped_column(sa.String(30), default="password")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(Utc, index=True)
    revoked_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)


class Run(Base):
    """One synthesis: the three inputs, their status, and the review outcome."""

    __tablename__ = "runs"

    id: Mapped[int] = _pk()
    #: Who submitted it. The placeholder account while login is off (ADR-022), so the
    #: run list and the config history always have a name to show.
    user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(sa.String(200), index=True)
    order_number: Mapped[str] = mapped_column(sa.String(100), index=True)
    configuration_id: Mapped[str] = mapped_column(sa.String(200), index=True)
    run_date: Mapped[Optional[dt.date]] = mapped_column(sa.Date, nullable=True)
    notes: Mapped[str] = mapped_column(sa.Text, default="")

    #: queued · running · needs_review · finalized · failed
    status: Mapped[str] = mapped_column(sa.String(30), default="queued", index=True)
    current_stage: Mapped[str] = mapped_column(sa.String(30), default="")
    error: Mapped[str] = mapped_column(sa.Text, default="")

    #: sha256 over every input file plus the active check versions. A matching submission
    #: shows the existing report first (``docs/design.md`` "LLM cost controls").
    input_fingerprint: Mapped[str] = mapped_column(sa.String(64), index=True, default="")
    rerun_reason: Mapped[str] = mapped_column(sa.Text, default="")
    cloned_from_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("runs.id"), nullable=True)
    config_last_modified: Mapped[str] = mapped_column(sa.String(64), default="")

    #: Which delivery programme this run belongs to: the ``code`` of a
    #: :class:`RunScope`, or empty when the submitter did not say (ADR-020).
    scope: Mapped[str] = mapped_column(sa.String(20), default="", index=True)
    #: Whether suppressions were applied to this delivery. Defaults to no, because
    #: assuming they were applied would let a missing suppression pass unremarked.
    has_suppressions: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    #: How many deliverables the campaign has, as the submitter states it. Zero means
    #: they did not say. Code checks it against the files uploaded, because a count
    #: the model is merely told is a count nobody verifies (ADR-021).
    deliverable_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    #: How many of those outputs this run is validating. Zero means they did not say.
    outputs_validated: Mapped[int] = mapped_column(sa.Integer, default=0)
    #: Anything else about the delivery the reviewer should know.
    delivery_notes: Mapped[str] = mapped_column(sa.Text, default="")
    #: The configuration notes in force when the run was submitted (ADR-024), copied
    #: here so the run page and the frozen report show what the model was told even
    #: after the note is edited or switched off.
    config_notes_snapshot: Mapped[Any] = mapped_column(Json, default=list)
    rules_version: Mapped[int] = mapped_column(sa.Integer, default=1)
    model_used: Mapped[str] = mapped_column(sa.String(200), default="")
    prompt_version: Mapped[str] = mapped_column(sa.String(20), default="")

    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True, index=True)

    summary: Mapped[str] = mapped_column(sa.Text, default="")
    top_issues: Mapped[Any] = mapped_column(Json, default=list)

    files: Mapped[list["RunFile"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    stages: Mapped[list["RunStage"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    rules: Mapped[list["Rule"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    elements: Mapped[list["ConfigElement"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    traces: Mapped[list["Trace"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RunFile(Base):
    """An uploaded input or a generated output, stored on the shared volume."""

    __tablename__ = "run_files"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    #: osl · config · dirt · field_distribution · state_distribution · counts · billing · report
    kind: Mapped[str] = mapped_column(sa.String(40))
    #: Position within the kind, from one. A campaign can deliver the same report
    #: type several times, one per segment or deliverable (ADR-021).
    part: Mapped[int] = mapped_column(sa.Integer, default=1)
    #: What the submitter called this file, used to name the part in a finding.
    part_label: Mapped[str] = mapped_column(sa.String(200), default="")
    filename: Mapped[str] = mapped_column(sa.String(500))
    storage_key: Mapped[str] = mapped_column(sa.String(500))
    sha256: Mapped[str] = mapped_column(sa.String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)

    run: Mapped[Run] = relationship(back_populates="files")


class Config(Base):
    """A captured ETL config, versioned per configuration id.

    Kept separately from runs so a config can outlive the retention window; the "copy
    config" action reads from here.
    """

    __tablename__ = "configs"
    __table_args__ = (sa.UniqueConstraint("configuration_id", "version", name="uq_config_version"),)

    id: Mapped[int] = _pk()
    configuration_id: Mapped[str] = mapped_column(sa.String(200), index=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    customer_name: Mapped[str] = mapped_column(sa.String(200), default="")
    content: Mapped[Any] = mapped_column(Json, default=dict)
    sha256: Mapped[str] = mapped_column(sa.String(64), index=True)
    last_modified: Mapped[str] = mapped_column(sa.String(64), default="")
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    #: The account behind ``created_by`` (ADR-022); the name is kept too, so the
    #: config history still reads after an account is renamed.
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class Rule(Base):
    """A canonical requirement, from the OSL, the config, or a user edit."""

    __tablename__ = "rules"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(sa.String(40), index=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    source: Mapped[str] = mapped_column(sa.String(20))
    rule: Mapped[Any] = mapped_column(Json)
    confidence: Mapped[float] = mapped_column(sa.Float, default=1.0)
    edited_by: Mapped[str] = mapped_column(sa.String(200), default="")
    edited_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)

    run: Mapped[Run] = relationship(back_populates="rules")


class ConfigElement(Base):
    """What one config block does, in requirement vocabulary."""

    __tablename__ = "config_elements"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    element_id: Mapped[str] = mapped_column(sa.String(40), index=True)
    json_path: Mapped[str] = mapped_column(sa.String(500))
    req_type: Mapped[str] = mapped_column(sa.String(40), default="")
    element: Mapped[Any] = mapped_column(Json)
    is_technical: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    run: Mapped[Run] = relationship(back_populates="elements")


class Trace(Base):
    """A link between an OSL requirement and a config element."""

    __tablename__ = "traces"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(sa.String(40), index=True)
    element_id: Mapped[Optional[str]] = mapped_column(sa.String(40), nullable=True)
    verdict: Mapped[str] = mapped_column(sa.String(30))
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    confidence: Mapped[float] = mapped_column(sa.Float, default=1.0)
    by_code: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    edited_by: Mapped[str] = mapped_column(sa.String(200), default="")

    run: Mapped[Run] = relationship(back_populates="traces")


class Finding(Base):
    """One potential issue, with its evidence and its review state."""

    __tablename__ = "findings"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[str] = mapped_column(sa.String(40))
    type: Mapped[str] = mapped_column(sa.String(50), index=True)
    severity: Mapped[str] = mapped_column(sa.String(20), index=True)
    title: Mapped[str] = mapped_column(sa.Text)
    detail: Mapped[str] = mapped_column(sa.Text, default="")
    leg: Mapped[str] = mapped_column(sa.String(30), default="osl_config")
    rule_ref: Mapped[str] = mapped_column(sa.String(40), default="")
    #: True while the rule behind it is in shadow: stored and counted, shown to
    #: nobody, which is how a new rule's precision is measured before it starts
    #: interrupting reviewers (ADR-021).
    shadow: Mapped[bool] = mapped_column(sa.Boolean, default=False, index=True)
    element_ref: Mapped[str] = mapped_column(sa.String(40), default="")
    evidence: Mapped[Any] = mapped_column(Json, default=dict)

    #: Which rules version produced this, so old reports stay reproducible.
    rules_version: Mapped[int] = mapped_column(sa.Integer, default=1)
    #: Who decided it (ADR-022). The placeholder while login is off.
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    #: undecided · confirmed · false_positive · accepted_risk
    review_status: Mapped[str] = mapped_column(sa.String(30), default="undecided", index=True)
    review_note: Mapped[str] = mapped_column(sa.Text, default="")
    reviewed_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    verified: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    verify_agreed: Mapped[Optional[bool]] = mapped_column(sa.Boolean, nullable=True)

    run: Mapped[Run] = relationship(back_populates="findings")


class RunStage(Base):
    """Per-stage status and timing; the resume point for a retried job."""

    __tablename__ = "run_stages"
    __table_args__ = (sa.UniqueConstraint("run_id", "stage", name="uq_run_stage"),)

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(sa.String(30))
    status: Mapped[str] = mapped_column(sa.String(20), default="pending")
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(sa.Integer, default=0)
    cache_hits: Mapped[int] = mapped_column(sa.Integer, default=0)
    tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    error: Mapped[str] = mapped_column(sa.Text, default="")

    run: Mapped[Run] = relationship(back_populates="stages")


class LlmCall(Base):
    """One row per model call: ids and counts only, never prompt text (ADR-003)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = _pk()
    run_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(sa.String(30), index=True)
    provider: Mapped[str] = mapped_column(sa.String(30))
    model: Mapped[str] = mapped_column(sa.String(200))
    prompt_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(sa.Integer, default=0)
    retries: Mapped[int] = mapped_column(sa.Integer, default=0)
    ok: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    cached: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    error: Mapped[str] = mapped_column(sa.String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)


class LlmCacheEntry(Base):
    """The stage cache: the same content is never sent to the model twice (ADR-005)."""

    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    stage: Mapped[str] = mapped_column(sa.String(30), index=True)
    text: Mapped[str] = mapped_column(sa.Text)
    data: Mapped[Any] = mapped_column(Json, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)
    hits: Mapped[int] = mapped_column(sa.Integer, default=0)


class AttributeAlias(Base):
    """Maps the names one attribute goes by onto a canonical name."""

    __tablename__ = "attribute_aliases"

    id: Mapped[int] = _pk()
    canonical_name: Mapped[str] = mapped_column(sa.String(200), index=True)
    alias: Mapped[str] = mapped_column(sa.String(200), index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(sa.String(200), nullable=True)


class MaskedColumn(Base):
    """A report column whose values are masked at parse time (ADR-003)."""

    __tablename__ = "masked_columns"

    id: Mapped[int] = _pk()
    pattern: Mapped[str] = mapped_column(sa.String(200), unique=True)
    description: Mapped[str] = mapped_column(sa.Text, default="")


class AuditLog(Base):
    """Who viewed, downloaded, reviewed, or edited what."""

    __tablename__ = "audit_log"

    id: Mapped[int] = _pk()
    user_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    #: The actor's display name, kept beside the id so the entry still reads after an
    #: account is renamed.
    actor: Mapped[str] = mapped_column(sa.String(200), default="")
    action: Mapped[str] = mapped_column(sa.String(60), index=True)
    run_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True, index=True)
    detail: Mapped[str] = mapped_column(sa.Text, default="")
    at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)


class ArtifactType(Base):
    """An input the tool accepts: the OSL, the config, or a report type (ADR-020).

    Report types are **data, not code**. An administrator adds one, describes what it
    is, writes the guidance the model should read it with, and switches it on; the
    upload form and the pipeline follow. Switching it off hides it from new runs
    without touching the runs that already used it.

    The OSL and the config are rows here too, so their descriptions and guidance are
    edited in the same place. Their keys are fixed because the pipeline reads them with
    dedicated parsers.
    """

    __tablename__ = "artifact_types"

    id: Mapped[int] = _pk()
    #: Stable identifier used as the multipart field name and the storage key.
    key: Mapped[str] = mapped_column(sa.String(60), unique=True, index=True)
    label: Mapped[str] = mapped_column(sa.String(120))
    #: osl · config · report. Only reports can be added or removed.
    kind: Mapped[str] = mapped_column(sa.String(20), default="report", index=True)

    #: What this artifact is, in a sentence, for whoever is uploading it.
    description: Mapped[str] = mapped_column(sa.Text, default="")
    #: What the model should pay attention to, in plain language. Empty means the
    #: pipeline behaves exactly as it did before this existed.
    ai_context: Mapped[str] = mapped_column(sa.Text, default="")

    #: Whether the upload slot appears on the new-run form.
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    #: Whether a run may be submitted without it.
    is_required: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    #: Whether this is one of the shipped types; a built-in may be disabled but not
    #: deleted, because its key is referenced by the fixed report checks.
    is_builtin: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=100)

    notes: Mapped[str] = mapped_column(sa.Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)

    samples: Mapped[list["ArtifactSample"]] = relationship(
        back_populates="artifact_type", cascade="all, delete-orphan", order_by="ArtifactSample.id"
    )


class ArtifactSample(Base):
    """One example of what an artifact type looks like (ADR-021).

    Up to three per type. Real report layouts vary between customers and one sample
    hides that, which is how a named value comes to work on the workbook it was
    written against and nothing else.
    """

    __tablename__ = "artifact_samples"

    id: Mapped[int] = _pk()
    artifact_type_id: Mapped[int] = mapped_column(
        sa.ForeignKey("artifact_types.id", ondelete="CASCADE"), index=True
    )
    #: What distinguishes this sample from the others, e.g. the customer or the year.
    label: Mapped[str] = mapped_column(sa.String(200), default="")
    filename: Mapped[str] = mapped_column(sa.String(500), default="")
    storage_path: Mapped[str] = mapped_column(sa.String(500), default="")
    sha256: Mapped[str] = mapped_column(sa.String(64), default="", index=True)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    #: The sheet names the workbook holds, read once at upload so the console and the
    #: type detector do not have to open the file again.
    sheets: Mapped[Any] = mapped_column(Json, default=list)
    notes: Mapped[str] = mapped_column(sa.Text, default="")
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    #: The uploader's name, kept beside the id so the list still reads after an
    #: account is renamed, the same as ``configs.created_by``.
    uploaded_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)

    artifact_type: Mapped[ArtifactType] = relationship(back_populates="samples")


class RunScope(Base):
    """A delivery programme, with the standing instructions that apply to it (ADR-020).

    Most customers fall into Account Monitoring, Account Solicitation, or Archives, and
    each carries compliance expectations that are true of every run in it and are
    usually *not* restated in the OSL. Holding them here means the model reads each
    delivery in the right regime instead of inferring one.
    """

    __tablename__ = "run_scopes"

    id: Mapped[int] = _pk()
    #: Short code shown in the UI and stored on the run, e.g. ``"AM"``.
    code: Mapped[str] = mapped_column(sa.String(20), unique=True, index=True)
    label: Mapped[str] = mapped_column(sa.String(120))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    #: Compliance expectations that hold for every run in this scope, in plain
    #: language. Passed to the model as context; never treated as an OSL requirement.
    standing_instructions: Mapped[str] = mapped_column(sa.Text, default="")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=100)


class NamedValueRow(Base):
    """A pointer into a report that checks refer to by name."""

    __tablename__ = "named_values"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(sa.String(100), unique=True, index=True)
    report_type: Mapped[str] = mapped_column(sa.String(40))
    sheet: Mapped[str] = mapped_column(sa.String(100))
    #: ``{"kind": "cell", "cell": "H9"}`` or ``{"kind": "label", "label": "...", ...}``
    locator: Mapped[Any] = mapped_column(Json, default=dict)
    description: Mapped[str] = mapped_column(sa.Text, default="")


class CheckDefinitionRow(Base):
    """An admin-defined cross-report check, versioned."""

    __tablename__ = "check_definitions"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(sa.String(100), index=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    kind: Mapped[str] = mapped_column(sa.String(20), default="expression")
    expression: Mapped[str] = mapped_column(sa.Text, default="")
    instruction: Mapped[str] = mapped_column(sa.Text, default="")
    reasoning: Mapped[str] = mapped_column(sa.Text, default="")
    severity: Mapped[str] = mapped_column(sa.String(20), default="medium")
    scope: Mapped[str] = mapped_column(sa.String(200), default="all")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    #: draft · shadow · active · disabled · deleted (ADR-021). ``is_active`` stays as
    #: the switch every existing query reads; this is the fuller lifecycle, and the
    #: two are kept consistent by the one function that moves a rule between states.
    state: Mapped[str] = mapped_column(sa.String(20), default="active", index=True)
    #: shipped · admin · learned. What a finding's explanation starts from.
    origin: Mapped[str] = mapped_column(sa.String(20), default="admin")
    candidate_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class ComplianceRuleRow(Base):
    """A rule that must be present in every config in scope."""

    __tablename__ = "compliance_rules"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(sa.String(100), unique=True)
    requirement: Mapped[Any] = mapped_column(Json, default=dict)
    scope: Mapped[str] = mapped_column(sa.String(200), default="all")
    reasoning: Mapped[str] = mapped_column(sa.Text, default="")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    #: draft · shadow · active · disabled · deleted (ADR-021).
    state: Mapped[str] = mapped_column(sa.String(20), default="active", index=True)
    origin: Mapped[str] = mapped_column(sa.String(20), default="admin")
    candidate_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True, index=True)


class ReversePassCategoryRow(Base):
    """Which config categories are checked back against the OSL."""

    __tablename__ = "reverse_pass_categories"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(sa.String(100), unique=True)
    kinds: Mapped[Any] = mapped_column(Json, default=list)
    checked: Mapped[bool] = mapped_column(sa.Boolean, default=True)


class FinalReport(Base):
    """The frozen one-page report. Stored once and never regenerated (ADR-005)."""

    __tablename__ = "final_reports"

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    html_path: Mapped[str] = mapped_column(sa.String(500))
    pdf_path: Mapped[str] = mapped_column(sa.String(500), default="")
    html_sha256: Mapped[str] = mapped_column(sa.String(64))
    verdict: Mapped[str] = mapped_column(sa.String(20))
    generated_by: Mapped[str] = mapped_column(sa.String(200), default="")
    generated_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    generated_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class TrainingObservation(Base):
    """One thing a person knows, in their own words, anchored to what they mean.

    The raw material of a learned rule (ADR-021). It never runs. It is never deleted
    either: synthesis marks it, and a rejection keeps it with its reason, because the
    record of what someone said is worth more than the row it occupies.
    """

    __tablename__ = "training_observations"

    id: Mapped[int] = _pk()
    run_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: The finding it was raised from, when a reviewer wrote it while deciding one.
    finding_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("findings.id", ondelete="SET NULL"), nullable=True
    )
    author_user_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    author: Mapped[str] = mapped_column(sa.String(200), default="")

    #: reconciliation · field_constraint · correction · note · config_note
    kind: Mapped[str] = mapped_column(sa.String(30), default="reconciliation", index=True)
    #: For a ``config_note``: the ETL configuration it follows (ADR-024). A note is
    #: guidance for every run of that configuration until it is switched off, and an
    #: observation in the queue at the same time.
    configuration_id: Mapped[str] = mapped_column(sa.String(200), default="", index=True)
    #: Whether a config note still applies. Switched off rather than deleted, so the
    #: record of what someone said survives.
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    #: Earlier wordings, oldest first: ``{"version", "statement", "at", "by"}``. An edit
    #: replaces the text and keeps what it replaced.
    revisions: Mapped[Any] = mapped_column(Json, default=list)
    #: The typed selections this points at: report cells, OSL sections, config paths.
    #: The anchor is what makes reliable synthesis possible; prose alone is a guess.
    anchors: Mapped[Any] = mapped_column(Json, default=list)
    #: What the person actually wrote. Treated as data, never as an instruction.
    statement: Mapped[str] = mapped_column(sa.Text, default="")
    expectation: Mapped[str] = mapped_column(sa.Text, default="")
    severity_hint: Mapped[str] = mapped_column(sa.String(20), default="medium")
    #: global · customer · programme. The narrowest that fits is the default.
    scope_hint: Mapped[str] = mapped_column(sa.String(30), default="customer")
    customer_name: Mapped[str] = mapped_column(sa.String(200), default="", index=True)
    scope_code: Mapped[str] = mapped_column(sa.String(20), default="")

    #: new · queued · synthesized · rejected · superseded. Forward only.
    status: Mapped[str] = mapped_column(sa.String(20), default="new", index=True)
    status_note: Mapped[str] = mapped_column(sa.Text, default="")
    #: Which candidate it fed, set when it is synthesized. The row itself is untouched.
    candidate_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    synthesized_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    #: Bumped on every edit; an observation is editable by its author until an
    #: administrator queues it, and the audit trail has to survive the convenience.
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, onupdate=utcnow)


class RuleCandidate(Base):
    """A rule the model drafted from observations, waiting for a person (ADR-021).

    It never runs. Code has already validated it by the time an administrator sees
    it, and approval is what turns it into a rule the pipeline evaluates.
    """

    __tablename__ = "rule_candidates"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(sa.String(120), default="")
    #: check · compliance_rule · field_constraint — which existing rule surface this
    #: becomes on approval. Training adds no second evaluator.
    target_kind: Mapped[str] = mapped_column(sa.String(30), default="check")
    #: The structured rule, shaped by the target kind's own schema.
    body: Mapped[Any] = mapped_column(Json, default=dict)
    reasoning: Mapped[str] = mapped_column(sa.Text, default="")
    severity: Mapped[str] = mapped_column(sa.String(20), default="medium")
    scope: Mapped[str] = mapped_column(sa.String(200), default="all")
    source_observation_ids: Mapped[Any] = mapped_column(Json, default=list)

    #: draft · approved · rejected. A rejected candidate keeps its sources so a later
    #: attempt can start from them.
    status: Mapped[str] = mapped_column(sa.String(20), default="draft", index=True)
    admin_note: Mapped[str] = mapped_column(sa.Text, default="")
    #: What the model produced, kept beside what was approved. The difference is the
    #: only measure of how much correcting the model needs.
    model_draft: Mapped[Any] = mapped_column(Json, default=dict)
    model_used: Mapped[str] = mapped_column(sa.String(200), default="")
    prompt_version: Mapped[str] = mapped_column(sa.String(20), default="")
    #: Overlaps with an active rule, found by fingerprint at approval time.
    conflicts: Mapped[Any] = mapped_column(Json, default=list)
    #: What a replay against the golden set and recent runs would have changed.
    replay: Mapped[Any] = mapped_column(Json, default=dict)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    decided_by: Mapped[str] = mapped_column(sa.String(200), default="")
    decided_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)


class FieldConstraint(Base):
    """A rule about one attribute, written in plain words and stored as data.

    "This field is never blank" is what people actually have to say. The human
    language is the input to synthesis; what runs is structured and evaluated by code
    (ADR-001, ADR-021).
    """

    __tablename__ = "field_constraints"

    id: Mapped[int] = _pk()
    #: The canonical attribute name, resolved through the alias table.
    field: Mapped[str] = mapped_column(sa.String(200), index=True)
    #: not_blank · allowed_values · forbidden_values · range · format · fill_rate_min
    constraint: Mapped[str] = mapped_column(sa.String(40))
    value: Mapped[Any] = mapped_column(Json, default=dict)
    #: Which report types it applies to; empty means every one that carries the field.
    report_kinds: Mapped[Any] = mapped_column(Json, default=list)
    severity: Mapped[str] = mapped_column(sa.String(20), default="medium")
    reasoning: Mapped[str] = mapped_column(sa.Text, default="")
    #: ``all``, a customer name, or ``programme:CODE``. The narrowest that fits.
    scope: Mapped[str] = mapped_column(sa.String(200), default="all")

    #: draft · shadow · active · disabled · deleted. See RuleLifecycle.
    state: Mapped[str] = mapped_column(sa.String(20), default="active", index=True)
    origin: Mapped[str] = mapped_column(sa.String(20), default="admin")
    candidate_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True, index=True)


class RuleStateChange(Base):
    """Every move a rule makes between states, and who made it (ADR-021).

    Nothing transitions by itself, so every row here has an actor. Under the EU AI
    Act's human-oversight provisions and the NIST AI Risk Management Framework the
    record of the human decision is itself the required artifact, and it is only
    cheap to keep if it is kept from the start.
    """

    __tablename__ = "rule_state_changes"

    id: Mapped[int] = _pk()
    #: check · compliance_rule · field_constraint
    rule_kind: Mapped[str] = mapped_column(sa.String(30), index=True)
    rule_id: Mapped[int] = mapped_column(sa.Integer, index=True)
    from_state: Mapped[str] = mapped_column(sa.String(20), default="")
    to_state: Mapped[str] = mapped_column(sa.String(20), default="")
    note: Mapped[str] = mapped_column(sa.Text, default="")
    actor_user_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    actor: Mapped[str] = mapped_column(sa.String(200), default="")
    at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)


class AppSetting(Base):
    """One setting an administrator has overridden (ADR-023).

    The table holds **overrides only**. A key that is absent falls through to the
    environment and then to the built-in default, so a fresh install behaves exactly
    as it did when the environment was the only source.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = _pk()
    key: Mapped[str] = mapped_column(sa.String(100), unique=True, index=True)
    #: The value, typed by the registry entry rather than by the column. A secret is
    #: stored here already encrypted and is never returned to a client.
    value: Mapped[Any] = mapped_column(Json, default=dict)
    is_secret: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    updated_by: Mapped[str] = mapped_column(sa.String(200), default="")


class ConfigChange(Base):
    """An append-only record of every settings change.

    Kept separately from ``audit_log`` because it carries the old value as well as the
    new one, which is what makes "revert to what it was" a button rather than an
    archaeology exercise.
    """

    __tablename__ = "config_changes"

    id: Mapped[int] = _pk()
    key: Mapped[str] = mapped_column(sa.String(100), index=True)
    #: Redacted for a secret: the point is that something changed and who changed it,
    #: never what the value was (ADR-023).
    old_value: Mapped[Any] = mapped_column(Json, default=dict)
    new_value: Mapped[Any] = mapped_column(Json, default=dict)
    changed_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    changed_by: Mapped[str] = mapped_column(sa.String(200), default="")
    changed_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)


class Job(Base):
    """The job queue, as an ordinary table (ADR-017).

    Claimed with ``FOR UPDATE SKIP LOCKED`` on Postgres and a guarded ``UPDATE`` on
    SQLite. Jobs survive a restart, which is the property that matters: a worker killed
    mid-run leaves a claimable row behind and the retry resumes at the last good stage.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = _pk()
    task: Mapped[str] = mapped_column(sa.String(60), index=True)
    run_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True, index=True)
    payload: Mapped[Any] = mapped_column(Json, default=dict)
    #: queued · running · done · failed
    status: Mapped[str] = mapped_column(sa.String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(sa.Integer, default=3)
    last_error: Mapped[str] = mapped_column(sa.Text, default="")
    #: Not claimable before this, which is how backoff between retries is expressed.
    run_after: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)
    locked_by: Mapped[str] = mapped_column(sa.String(100), default="")
    locked_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
