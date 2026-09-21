"""SQLAlchemy models: every table in ``docs/design.md`` "Data model".

Portable across SQLite and Postgres (ADR-017): JSON columns use the variant in
:mod:`greenlight_ai.db.types`, timestamps come back timezone-aware on both, and no
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

from greenlight_ai import scopes
from greenlight_ai.db.types import Json, Utc, utcnow

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
    "DefinitionVersion",
    "MeaningEntry",
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
    #: The roles this account holds, weakest first: any of ``user``, ``reviewer``,
    #: ``admin`` (ADR-049). Capabilities are the union, so holding more never takes
    #: anything away, and `auth/roles.py` is the only place that says what each grants.
    #:
    #: The only answer. A single ``role`` column stood beside it while the callers were
    #: moved over and was dropped in `d2f4a6b8c0e1`: two answers to one question is
    #: where the two get to disagree, and an account behaving as an administrator while
    #: its row says otherwise is how somebody gets locked out.
    roles: Mapped[Any] = mapped_column(Json, default=lambda: ["user"])
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
    #: The credit date the delivery is cut as of. Stage 7 checks that the artifacts,
    #: the reports above all, carry it somewhere (ADR-027).
    credit_date: Mapped[Optional[dt.date]] = mapped_column(sa.Date, nullable=True)
    notes: Mapped[str] = mapped_column(sa.Text, default="")

    #: held · queued · running · needs_review · finalized · failed. A run is ``held``
    #: when the artifacts disagree with what the submitter typed (ADR-041): the files
    #: are stored and the run exists, and it waits for somebody to accept the
    #: disagreement rather than being thrown away and re-uploaded.
    status: Mapped[str] = mapped_column(sa.String(30), default="queued", index=True)
    current_stage: Mapped[str] = mapped_column(sa.String(30), default="")
    #: One line, shown in the runs list and at the top of the run: what went wrong.
    error: Mapped[str] = mapped_column(sa.Text, default="")
    #: The same failure at length, for somebody trying to trace it: which stage, which
    #: attempt, and the traceback through this codebase. Shown only on the run itself,
    #: behind a disclosure, and never in the list. It carries frames and an exception
    #: message — never a row from a delivery, which is ADR-003 and is why the pipeline
    #: raises with counts and ids rather than with values.
    error_detail: Mapped[str] = mapped_column(sa.Text, default="")

    #: sha256 over every input file plus the active check versions. A matching submission
    #: shows the existing report first (``docs/design.md`` "LLM cost controls").
    input_fingerprint: Mapped[str] = mapped_column(sa.String(64), index=True, default="")
    rerun_reason: Mapped[str] = mapped_column(sa.Text, default="")
    cloned_from_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("runs.id"), nullable=True)
    config_last_modified: Mapped[str] = mapped_column(sa.String(64), default="")

    #: Which delivery programme this run belongs to: the ``code`` of a
    #: :class:`RunScope`, or empty when the submitter did not say (ADR-020).
    scope: Mapped[str] = mapped_column(sa.String(20), default="", index=True)
    #: Words the model quoted from this delivery that would have matched its declared
    #: programme, by programme code (Phase 6.18f, ADR-045). A suggestion, never an
    #: application: an administrator adds them to the word list, or does not. Kept on
    #: the run because that is where the evidence for them is.
    keyword_suggestions: Mapped[Any] = mapped_column(Json, default=dict)
    #: The counts report's step-by-step flow, read while the workbooks were open
    #: (Phase 6.21f). The frozen report has had a Waterfall section since Phase 5 and
    #: was passed an empty list, so it has never been drawn: by render time the
    #: workbooks are parsed and gone, and the flow has to be stored with the run.
    waterfall: Mapped[Any] = mapped_column(Json, default=list)
    #: The shape of what this delivery carried, per attribute: a null rate, a
    #: minimum, a maximum and a mean (Phase 6.21c). **Aggregates only** — never a row,
    #: never which record held the minimum (ADR-003). A later run of the same
    #: configuration is compared against these, which is the only honest baseline for
    #: a finding no rule covers.
    attribute_profile: Mapped[Any] = mapped_column(Json, default=dict)
    #: Names the model read for this run because four deterministic rungs could not
    #: (Phase 6.21b, ADR-054): one entry per artifact, kind, wanted name and what was
    #: used. A suggestion, never an application — an administrator records it on the
    #: artifact type, or does not. Kept on the run, like the keyword suggestions
    #: above, because that is where the evidence for it is.
    layout_suggestions: Mapped[Any] = mapped_column(Json, default=list)
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
    #: Which version of each definition the run was processed under, as
    #: ``{"artifact_type:<key>": n, "programme_rules:<code>": n}`` (ADR-029). A
    #: finding on an old run still points at the definition that produced it.
    definition_versions: Mapped[Any] = mapped_column(Json, default=dict)
    rules_version: Mapped[int] = mapped_column(sa.Integer, default=1)
    model_used: Mapped[str] = mapped_column(sa.String(200), default="")
    prompt_version: Mapped[str] = mapped_column(sa.String(20), default="")

    #: What the run checked and what it did not: one entry per requirement with its
    #: state and the reason (Phase 6.11c). Absence of a finding is not a pass, and
    #: this is the column that says so.
    coverage: Mapped[Any] = mapped_column(Json, default=list)
    #: How many checks produced a verdict against each uploaded report. A report with
    #: none arrived and was asked nothing.
    report_coverage: Mapped[Any] = mapped_column(Json, default=list)
    #: Run-level things the reviewer must be told that are not findings: a second
    #: opinion that could not be obtained, a programme reading that did not run.
    notices: Mapped[Any] = mapped_column(Json, default=list)

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
    #: ``code`` or ``model`` — which path produced this finding (Phase 6.16).
    #: Not who decided it: code decides every severity (ADR-001). It says whether
    #: a comparison reached the answer on its own, or the model read something
    #: first, so the cost and the reliability of each path are visible rather than
    #: inferred from a token count.
    engine: Mapped[str] = mapped_column(sa.String(10), default="code", index=True)
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
    #: How sure the tool is, 0–1, or NULL where the question does not arise
    #: (Phase 6.21f). Not a severity: a comparison code is certain about can be
    #: trivial, and a reading the model was unsure of can be the thing that matters.
    confidence: Mapped[Optional[float]] = mapped_column(sa.Float, nullable=True)
    #: What each of stage 8's lenses said (Phase 6.11e). Empty for a run verified by
    #: the single second opinion.
    lens_opinions: Mapped[Any] = mapped_column(Json, default=list)

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

    #: The validation guide: ordered entries saying what a cell means and where it
    #: answers to (Phase 6.8b). Empty means the model reads the report as it always
    #: did; a concrete entry also compiles into a shadow check.
    guide_entries: Mapped[Any] = mapped_column(Json, default=list)

    #: What a delivery calls each sheet, column and row label the fixed checks look
    #: for (Phase 6.21b). Ordered entries, each naming a scope, a kind, the name the
    #: checks ask for, and the spellings that also mean it. Empty is the ordinary
    #: state on a new deployment and stays empty for a delivery whose layout the
    #: ladder resolves in code (ADR-054); it fills as administrators accept what the
    #: ladder had to reason about, and every entry it gains removes a model call from
    #: every later run.
    layout_entries: Mapped[Any] = mapped_column(Json, default=list)

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
    #: The delivery programme this sample belongs to, or "" for a global one
    #: (Phase 6.10). Three samples per type per programme.
    scope_code: Mapped[str] = mapped_column(sa.String(20), default="", index=True)
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
    #: Words and phrases that mark a delivery as belonging to this programme. The
    #: classification check scans the OSL, the configuration, and the report headers
    #: for them; a run declared as one programme with none of its words and plenty of
    #: another's gets a finding (ADR-026).
    keywords: Mapped[Any] = mapped_column(Json, default=list)
    description: Mapped[str] = mapped_column(sa.Text, default="")
    #: Compliance expectations that hold for every run in this scope, in plain
    #: language. Passed to the model as context; never treated as an OSL requirement.
    standing_instructions: Mapped[str] = mapped_column(sa.Text, default="")
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=100)
    #: Whether a run in this programme needs a **second** person to approve before it
    #: can be frozen, when the first reviewer waved through something the programme
    #: treats as serious: a `must` programme-rule breach or a compliance finding
    #: marked OK. Off by default, and meaningless with login off, since both people
    #: would be the same placeholder account (ADR-036).
    second_approver: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class SecondApproval(Base):
    """A second person has looked at what the first waved through (ADR-036).

    Not a re-review. The first reviewer decided; this records that somebody else, who
    is not them, saw the decisions the programme treats as serious and agreed the run
    can be frozen. It is the lightest form of the control that is worth anything: a
    signature from a different person.
    """

    __tablename__ = "second_approvals"
    __table_args__ = (sa.UniqueConstraint("run_id", name="uq_second_approval_run"),)

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    actor: Mapped[str] = mapped_column(sa.String(200), default="")
    actor_user_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(sa.Text, default="")
    #: What they were shown: the finding ids the programme treats as serious that the
    #: first reviewer marked OK. Stored so the record says what was approved, not
    #: merely that something was.
    covered: Mapped[Any] = mapped_column(Json, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


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
    #: For a judgment check: the named values the model may see, and nothing else
    #: (Phase 6.13c, ADR-039). The model judges those values against the instruction;
    #: code records the verdict.
    value_names: Mapped[Any] = mapped_column(Json, default=list, nullable=True)
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
    #: Bumped on every edit (ADR-032); a finding records the version that produced it.
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
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
    #: What the person confirmed when they froze it (Phase 6.11d): the coverage
    #: counts, the unevaluated checks, the shadow rules and definition versions in
    #: force, and the run's notices. Stored because a report that is evidence of a
    #: review should say what the reviewer was shown.
    attestation: Mapped[Any] = mapped_column(Json, default=dict)
    generated_by: Mapped[str] = mapped_column(sa.String(200), default="")
    generated_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    generated_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class CoverageAcknowledgement(Base):
    """A person has seen that something was not checked (Phase 6.11d).

    The finalize gate needs one of these for every requirement no report evidenced and
    every check that could not be evaluated. It is not a decision that the delivery is
    fine; it is the record that the gap was in front of somebody before the report was
    frozen.
    """

    __tablename__ = "coverage_acknowledgements"
    __table_args__ = (sa.UniqueConstraint("run_id", "target", name="uq_coverage_ack_run_target"),)

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    #: A requirement id for a coverage gap, a finding id for a check that could not be
    #: evaluated. One column for both, because the gate asks the same question of each.
    target: Mapped[str] = mapped_column(sa.String(40))
    #: ``requirement`` or ``finding``.
    kind: Mapped[str] = mapped_column(sa.String(20), default="requirement")
    note: Mapped[str] = mapped_column(sa.Text, default="")
    actor: Mapped[str] = mapped_column(sa.String(200), default="")
    actor_user_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class Announcement(Base):
    """A message an administrator puts at the top of an app for a while.

    "Maintenance starts at 11pm on the 6th." The tool cannot know that, nobody should
    have to deploy to say it, and an email is read by whoever happens to open it. A
    scheduled banner is read by whoever is actually using the app when it matters.

    Scheduling is part of it rather than a convenience: a notice nobody remembers to
    take down is how an app comes to carry a stale warning for a month, which teaches
    people to stop reading banners at all.
    """

    __tablename__ = "announcements"

    id: Mapped[int] = _pk()
    #: ``info`` · ``warning`` · ``critical``. Chosen by the author; the apps render
    #: each differently and none of them is dismissible, because a notice somebody
    #: scheduled is a notice they wanted seen.
    level: Mapped[str] = mapped_column(sa.String(20), default="info", index=True)
    #: Who sees it: ``user``, ``admin`` or ``both``. The two apps have different
    #: audiences and most messages are for one of them.
    audience: Mapped[str] = mapped_column(sa.String(20), default="both", index=True)
    message: Mapped[str] = mapped_column(sa.Text, default="")

    #: When it starts and stops showing. Both are required: a banner with no end is
    #: the stale-notice problem this is meant to avoid.
    starts_at: Mapped[dt.datetime] = mapped_column(Utc)
    ends_at: Mapped[dt.datetime] = mapped_column(Utc)
    #: An off switch that does not lose the row, so a scheduled notice can be pulled
    #: without retyping it next month.
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)

    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class FieldLabel(Base):
    """What a delivery calls one of the fields the tool checks (Phase 6.14b).

    The credit date is written *as-of date*, *data date*, *cycle date* or *extract
    date* depending on who built the report. These are document labels, not data
    attributes, so they are not ``attribute_aliases``: that table resolves attribute
    names and loads as global-plus-customer only, and is the one table that never
    adopted the scope vocabulary (ADR-029). These use it.
    """

    __tablename__ = "field_labels"
    __table_args__ = (sa.UniqueConstraint("canonical", "label", "scope", name="uq_field_label"),)

    id: Mapped[int] = _pk()
    #: Which field this names. A closed set; ``credit_date`` is the first.
    canonical: Mapped[str] = mapped_column(sa.String(40), index=True)
    #: The label as it appears in a document, e.g. ``"As-of date"``. Matched with
    #: punctuation and case ignored, so one spelling covers several.
    label: Mapped[str] = mapped_column(sa.String(200))
    #: Where it applies, as a scope token (``everywhere``, ``programme:CODE``,
    #: ``customer:NAME``, ``config:ID``).
    scope: Mapped[str] = mapped_column(sa.String(120), default="everywhere", index=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


class ArtifactMismatch(Base):
    """The artifacts disagreed with what the submitter typed (ADR-041).

    One row per field that did not agree, written before the run is allowed to start.
    A row with no ``accepted_at`` is why the run is ``held``; accepting fills the
    reason and lets it queue. Rows are never deleted, so the review screen and the
    frozen report can both show that somebody waived the question and why.
    """

    __tablename__ = "artifact_mismatches"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "field", name="uq_artifact_mismatch_run_field"),
    )

    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    #: One of ``checks.artifact_match.MATCH_FIELDS``.
    field: Mapped[str] = mapped_column(sa.String(40))
    #: What the person typed, verbatim.
    submitted: Mapped[str] = mapped_column(sa.String(400), default="")
    #: What the artifact declares, verbatim.
    declared: Mapped[str] = mapped_column(sa.String(400), default="")
    #: ``near`` or ``different``. A ``match`` never becomes a row.
    kind: Mapped[str] = mapped_column(sa.String(20), default="different")
    #: Where the declared value was read from, in words a person can act on.
    source: Mapped[str] = mapped_column(sa.String(200), default="")

    #: Why it was accepted. Empty until somebody accepts it.
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    accepted_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    accepted_by: Mapped[str] = mapped_column(sa.String(200), default="")
    accepted_by_user_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)


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

    #: new · synthesized · rejected · withdrawn. Forward only. ``withdrawn`` means
    #: an administrator took it out of the queue so its author could write a fresh
    #: one — the row survives, because nothing in the training record is deleted.
    status: Mapped[str] = mapped_column(sa.String(20), default="new", index=True)
    status_note: Mapped[str] = mapped_column(sa.Text, default="")
    #: Which candidate it fed, set when it is synthesized. The row itself is untouched.
    candidate_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    synthesized_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    #: Bumped on every edit. Feedback is submitted once: after that only an
    #: administrator can correct the wording, and the audit trail has to survive it.
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
    #: Overlaps with an existing rule, found by fingerprint at synthesis and found again
    #: at approval, because a rule created in between is exactly what the gate is for.
    conflicts: Mapped[Any] = mapped_column(Json, default=list)
    #: What the rule would have done to recent finalized runs, evaluated against
    #: their stored reports and configuration rather than estimated (Phase 6.13e).
    replay: Mapped[Any] = mapped_column(Json, default=dict)
    #: What the critique pass said about the first draft (Phase 6.11g): whether it
    #: said what the statements said, and whether it overlaps a rule that exists.
    critique: Mapped[Any] = mapped_column(Json, default=dict)
    #: The rule after at most one redraft, when the critique asked for one. Empty
    #: when the first draft stood. ``model_draft`` is always the first attempt, so
    #: the distance between them is visible.
    redraft: Mapped[Any] = mapped_column(Json, default=dict)

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
    #: A scope token (:mod:`greenlight_ai.scopes`). The narrowest that fits.
    scope: Mapped[str] = mapped_column(sa.String(200), default="all")

    #: draft · shadow · active · disabled · deleted. See RuleLifecycle.
    state: Mapped[str] = mapped_column(sa.String(20), default="active", index=True)
    origin: Mapped[str] = mapped_column(sa.String(20), default="admin")
    candidate_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True, index=True)


class ProgrammeRule(Base):
    """A rule true of every delivery in a programme, written in plain words (ADR-026).

    The model reads for breaches; code sets the severity from the strictness, so the
    model never grades. Several per programme, each with its own strictness.
    """

    __tablename__ = "programme_rules"

    id: Mapped[int] = _pk()
    scope_code: Mapped[str] = mapped_column(sa.String(20), index=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    text: Mapped[str] = mapped_column(sa.Text, default="")
    #: must · should · advisory. Maps to high, medium, low.
    strictness: Mapped[str] = mapped_column(sa.String(20), default="should")
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=100)
    #: draft · shadow · active · disabled · deleted (ADR-021).
    state: Mapped[str] = mapped_column(sa.String(20), default="active", index=True)
    origin: Mapped[str] = mapped_column(sa.String(20), default="admin")
    candidate_id: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    scope: Mapped[str] = mapped_column(sa.String(200), default="all")
    reasoning: Mapped[str] = mapped_column(sa.Text, default="")
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    deleted_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True, index=True)


class MeaningEntry(Base):
    """One requirement mapping: OSL section → config block → report cells (Phase 6.10).

    Proposed by the model from the samples in scope, or written by hand; confirmed by
    an administrator. A confirmed entry with a config path, a report cell that
    resolves on a sample and a comparison compiles into a shadow check (ADR-021,
    ADR-033). Cell-level meaning (the validation guide) stays on the artifact type.
    """

    __tablename__ = "meaning_entries"
    __table_args__ = (sa.UniqueConstraint("scope_code", "key", name="uq_meaning_entry"),)

    id: Mapped[int] = _pk()
    #: "" for global, else the programme code. A programme entry with the same key
    #: as a global one overrides it at run time.
    scope_code: Mapped[str] = mapped_column(sa.String(20), default="", index=True)
    #: A stable slug for the requirement, e.g. ``geography``.
    key: Mapped[str] = mapped_column(sa.String(80))
    osl_section: Mapped[str] = mapped_column(sa.String(40), default="")
    osl_phrase: Mapped[str] = mapped_column(sa.String(300), default="")
    requirement_text: Mapped[str] = mapped_column(sa.Text, default="")
    config_path: Mapped[str] = mapped_column(sa.String(200), default="")
    #: Report cells that evidence it: ``[{report_key, sheet, kind, cell, label,
    #: label_column, value_column}]``.
    report_cells: Mapped[Any] = mapped_column(Json, default=list)
    meaning: Mapped[str] = mapped_column(sa.Text, default="")
    validate: Mapped[str] = mapped_column(sa.Text, default="")
    #: "" · equals · reconciles; what code checks between the first report cell and
    #: the config value.
    comparison: Mapped[str] = mapped_column(sa.String(20), default="")
    tolerance: Mapped[float] = mapped_column(sa.Float, default=0.0)
    #: Filled by code from the samples: ``[{sample_id, label, value}]``.
    examples: Mapped[Any] = mapped_column(Json, default=list)
    #: A compliance rule the model suggested: ``{name, json_path_contains, reasoning}``
    #: or null.
    compliance_suggestion: Mapped[Any] = mapped_column(Json, nullable=True)
    #: proposed · open · confirmed · rejected.
    status: Mapped[str] = mapped_column(sa.String(20), default="proposed", index=True)
    #: The model's question when it could not place the requirement.
    question: Mapped[str] = mapped_column(sa.Text, default="")
    #: The administrator's note.
    note: Mapped[str] = mapped_column(sa.Text, default="")
    confidence: Mapped[float] = mapped_column(sa.Float, default=0.0)
    proposed_by: Mapped[str] = mapped_column(sa.String(20), default="model")
    confirmed_by: Mapped[str] = mapped_column(sa.String(200), default="")
    confirmed_at: Mapped[Optional[dt.datetime]] = mapped_column(Utc, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, onupdate=utcnow)


class PromptExample(Base):
    """One worked example an administrator gives the model (Phase 6.13d, ADR-038).

    The built-in examples in :mod:`greenlight_ai.llm.prompts` are the floor; these are
    added after them, at most four per stage, most specific scope first. The answer was
    validated against the stage's own schema before this row was written, because an
    example the schema rejects teaches the model a shape the pipeline cannot parse.

    An example shows; it never instructs. Nothing here is a rule: the rules the engine
    runs live in the rule tables and are evaluated by code (ADR-001).
    """

    __tablename__ = "prompt_examples"

    id: Mapped[int] = _pk()
    #: A stage from :data:`greenlight_ai.llm.examples.EXAMPLE_STAGES`.
    stage: Mapped[str] = mapped_column(sa.String(40), index=True)
    #: Where it applies, as a scope token (ADR-037).
    scope: Mapped[str] = mapped_column(sa.String(120), default=scopes.EVERYWHERE, index=True)
    #: What the model would be shown, keyed by the stage's field names.
    given: Mapped[Any] = mapped_column(Json, default=dict)
    #: The answer to teach, as the stage's schema dumps it.
    answer: Mapped[Any] = mapped_column(Json, default=dict)
    #: Why it is here. For the next administrator; never rendered into a prompt.
    note: Mapped[str] = mapped_column(sa.Text, default="")
    #: ``admin``, or ``promoted:<kind>:<id>`` when it came from a decision a person
    #: had already confirmed. Nothing is promoted without somebody clicking.
    origin: Mapped[str] = mapped_column(sa.String(60), default="admin", index=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    updated_by: Mapped[str] = mapped_column(sa.String(200), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, onupdate=utcnow)


class DefinitionVersion(Base):
    """One snapshot of a definition an administrator edits (Phase 6.8c, ADR-029).

    Taken after every save of an artifact type (its fields, samples, and guide) and
    after every change to a programme's rule set. Ten are listed per object; a
    version a run inside the retention window still references is kept beyond the
    ten. A revert writes an old snapshot back as the next version, so nothing here
    is ever overwritten.
    """

    __tablename__ = "definition_versions"
    __table_args__ = (
        sa.UniqueConstraint("kind", "object_key", "version", name="uq_definition_version"),
    )

    id: Mapped[int] = _pk()
    #: ``artifact_type`` or ``programme_rules``.
    kind: Mapped[str] = mapped_column(sa.String(30), index=True)
    #: The artifact type's key, or the programme's code.
    object_key: Mapped[str] = mapped_column(sa.String(60), index=True)
    version: Mapped[int] = mapped_column(sa.Integer)
    #: The whole state after the save, as JSON. Ids, names and paths; never a file.
    snapshot: Mapped[Any] = mapped_column(Json, default=dict)
    #: One line saying what changed from the version before.
    summary: Mapped[str] = mapped_column(sa.String(500), default="")
    #: When this version was written back from an older one, which one.
    reverted_from: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(sa.String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)


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


class FindingSignatureState(Base):
    """What people have decided about one recurring finding (Phase 6.18a).

    A **signature** is the identity of "this same finding again": one customer, one
    delivery programme, one rule, and one thing it fired on. The row holds the verdicts
    people gave it and what code concluded from them — see `training/demotion.py` for
    the rules and the reasoning behind each.

    The row is a cache of an answer derivable from `findings` and `runs`, kept because
    a demotion has to be explainable months later: ``justified_by_run_ids`` names the
    runs whose verdicts it rests on, and ``reason`` is the sentence a reviewer is owed.

    **In 6.18a the state is recorded and acted on by nobody.** Every reviewer still sees
    every finding; this measures what demotion *would* do so that the question can be
    asked from evidence before it changes anybody's screen (ADR-043).
    """

    __tablename__ = "finding_signatures"

    id: Mapped[int] = _pk()
    #: The digest from :func:`greenlight_ai.training.demotion.signature`.
    signature: Mapped[str] = mapped_column(sa.String(40), unique=True, index=True)

    #: The parts, stored so a person can read what the digest stands for.
    customer_name: Mapped[str] = mapped_column(sa.String(200), index=True, default="")
    scope: Mapped[str] = mapped_column(sa.String(20), index=True, default="")
    rule_ref: Mapped[str] = mapped_column(sa.String(40), default="")
    finding_type: Mapped[str] = mapped_column(sa.String(50), default="")
    element_ref: Mapped[str] = mapped_column(sa.String(40), default="")

    #: watching · would_demote · blocked
    state: Mapped[str] = mapped_column(sa.String(20), default="watching", index=True)
    #: One sentence saying why it is in that state. A demotion nobody can explain is
    #: one nobody should trust.
    reason: Mapped[str] = mapped_column(sa.Text, default="")

    occurrences: Mapped[int] = mapped_column(sa.Integer, default=0)
    dismissed: Mapped[int] = mapped_column(sa.Integer, default=0)
    upheld: Mapped[int] = mapped_column(sa.Integer, default=0)
    #: The severities it has fired at, so the never-demoted floor is auditable.
    severities: Mapped[Any] = mapped_column(Json, default=list)
    #: The runs whose verdicts this rests on — the evidence, by id.
    justified_by_run_ids: Mapped[Any] = mapped_column(Json, default=list)

    first_seen: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow)
    last_seen: Mapped[dt.datetime] = mapped_column(Utc, default=utcnow, index=True)
