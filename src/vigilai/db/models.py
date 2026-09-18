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
    """Empty and unused in v1; the provision for adding login later (ADR-008)."""

    __tablename__ = "users"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(sa.String(200), default="")
    email: Mapped[str] = mapped_column(sa.String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(200), default="")
    role: Mapped[str] = mapped_column(sa.String(50), default="user")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class Run(Base):
    """One synthesis: the three inputs, their status, and the review outcome."""

    __tablename__ = "runs"

    id: Mapped[int] = _pk()
    user_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
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
    element_ref: Mapped[str] = mapped_column(sa.String(40), default="")
    evidence: Mapped[Any] = mapped_column(Json, default=dict)

    #: Which rules version produced this, so old reports stay reproducible.
    rules_version: Mapped[int] = mapped_column(sa.Integer, default=1)
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

    #: The uploaded sample, which named values are resolved against.
    filename: Mapped[str] = mapped_column(sa.String(500), default="")
    storage_path: Mapped[str] = mapped_column(sa.String(500), default="")
    notes: Mapped[str] = mapped_column(sa.Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


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
    generated_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


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
