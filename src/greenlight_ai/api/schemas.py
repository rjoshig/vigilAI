"""Wire models for the API.

Pydantic at the boundary only (standards/python.md). These are deliberately separate
from the canonical rule schema: the wire format can gain a field for the UI without
changing what the pipeline compares.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "NewRunOptions",
    "ArtifactSlot",
    "ScopeOption",
    "RunSummary",
    "RunDetail",
    "StageInfo",
    "FindingOut",
    "FindingPatch",
    "RuleOut",
    "TraceOut",
    "RequirementsOut",
    "RequirementEdit",
    "RequirementsPut",
    "RunStats",
    "ConfigSummary",
    "ConfigDetail",
    "DuplicateRun",
    "CreateRunResult",
    "CloneResult",
    "RecheckResult",
]


class StageInfo(BaseModel):
    """One stage's status and cost."""

    model_config = ConfigDict(from_attributes=True)

    stage: str
    status: str
    duration_ms: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    tokens: int = 0
    error: str = ""


class RunSummary(BaseModel):
    """A run as the Runs list shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_name: str
    order_number: str
    configuration_id: str
    status: str
    current_stage: str = ""
    error: str = ""
    created_at: dt.datetime
    finished_at: Optional[dt.datetime] = None
    high: int = 0
    medium: int = 0
    low: int = 0
    review: int = 0
    queue_position: Optional[int] = None
    #: Who submitted it. The placeholder's name while login is off (ADR-022).
    submitted_by: str = ""
    #: Which delivery programme this run belongs to, e.g. "AM" (ADR-020).
    scope: str = ""
    scope_label: str = ""


class RunDetail(RunSummary):
    """A run with everything the Review screen needs up front."""

    notes: str = ""
    #: The credit date the delivery is cut as of; checked against the artifacts.
    credit_date: Optional[dt.date] = None
    rules_version: int = 1
    model_used: str = ""
    prompt_version: str = ""
    summary: str = ""
    top_issues: list[str] = Field(default_factory=list)
    rerun_reason: str = ""
    input_fingerprint: str = ""
    #: Whether the submitter said suppressions were applied to this delivery.
    has_suppressions: bool = False
    #: The configuration notes in force when the run was submitted (ADR-024).
    config_notes: list[str] = Field(default_factory=list)
    can_finalize: bool = False
    finalized: bool = False
    #: Whether this deployment can render a PDF at all. False when the optional [pdf]
    #: extra is not installed, which is a deployment fact, not a per-run one.
    pdf_available: bool = False
    stages: list[StageInfo] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)


class FindingOut(BaseModel):
    """One finding, with its evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    finding_id: str
    type: str
    severity: str
    title: str
    detail: str = ""
    leg: str = "osl_config"
    rule_ref: str = ""
    element_ref: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    rules_version: int = 1
    review_status: str = "undecided"
    review_note: str = ""
    verified: bool = False
    verify_agreed: Optional[bool] = None


class FindingPatch(BaseModel):
    """A reviewer's decision on one finding."""

    model_config = ConfigDict(extra="forbid")

    review_status: Literal["undecided", "confirmed", "false_positive", "accepted_risk"]
    review_note: str = ""


class RuleOut(BaseModel):
    """One requirement, as the traceability matrix shows it."""

    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    source: str
    req_type: str
    summary: str = ""
    confidence: float = 1.0
    source_ref: str = ""
    source_text: str = ""
    rule: dict[str, Any] = Field(default_factory=dict)


class TraceOut(BaseModel):
    """One requirement-to-element link."""

    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    element_id: Optional[str] = None
    verdict: str
    reason: str = ""
    confidence: float = 1.0
    by_code: bool = False


class RequirementsOut(BaseModel):
    """The traceability matrix payload."""

    rules: list[RuleOut] = Field(default_factory=list)
    traces: list[TraceOut] = Field(default_factory=list)
    elements: list[dict[str, Any]] = Field(default_factory=list)
    rules_version: int = 1


class RequirementEdit(BaseModel):
    """An edit to one requirement or its trace link."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    rule: Optional[dict[str, Any]] = None
    element_id: Optional[str] = None
    clear_link: bool = False
    reason: str = ""


class RequirementsPut(BaseModel):
    """A batch of edits, applied as one version bump."""

    model_config = ConfigDict(extra="forbid")

    edits: list[RequirementEdit] = Field(min_length=1)


class RunStats(BaseModel):
    """Stage timings, calls, tokens, and cache hits."""

    run_id: int
    total_duration_ms: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stages: list[StageInfo] = Field(default_factory=list)


class ConfigSummary(BaseModel):
    """A captured config, as Config history lists it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    configuration_id: str
    version: int
    customer_name: str = ""
    sha256: str
    last_modified: str = ""
    created_at: dt.datetime
    run_count: int = 0
    #: Who ran the submission that captured this version (ADR-022).
    created_by: str = ""


class ConfigDetail(ConfigSummary):
    """A captured config with its content."""

    content: dict[str, Any] = Field(default_factory=dict)


class DuplicateRun(BaseModel):
    """The existing run a duplicate submission matched."""

    run_id: int
    status: str
    created_at: dt.datetime
    message: str


class CreateRunResult(BaseModel):
    """What `POST /runs` returns."""

    run_id: Optional[int] = None
    status: str = ""
    queue_position: Optional[int] = None
    duplicate: Optional[DuplicateRun] = None


class CloneResult(BaseModel):
    """What `POST /runs/{id}/clone` returns."""

    run_id: int
    cloned_from: int
    status: str


class RecheckResult(BaseModel):
    """What `POST /runs/{id}/recheck` returns."""

    run_id: int
    rules_version: int
    queued: bool
    findings: int = 0


class ArtifactSlot(BaseModel):
    """One upload slot the new-run form should offer (ADR-020)."""

    key: str
    label: str
    kind: str
    description: str = ""
    is_required: bool = False
    accept: str = ".xlsx"


class ScopeOption(BaseModel):
    """One delivery programme the new-run form should offer."""

    code: str
    label: str
    description: str = ""


class NewRunOptions(BaseModel):
    """What the new-run form needs in order to draw itself.

    The form is generated from this rather than hardcoded, so switching a report type
    off in the admin console removes its upload slot without a deploy.
    """

    artifacts: list[ArtifactSlot] = Field(default_factory=list)
    scopes: list[ScopeOption] = Field(default_factory=list)


class DetectedCandidate(BaseModel):
    """One artifact type an uploaded workbook might be."""

    key: str
    label: str
    score: float


class DetectedSheet(BaseModel):
    """What one tab of the workbook looks like, scored on its own.

    A multi-tab file can hold several report types, so each sheet gets its own verdict.
    """

    sheet: str
    verdict: str
    reason: str = ""
    key: Optional[str] = None
    label: Optional[str] = None
    score: float = 0.0


class TypeDetection(BaseModel):
    """What `POST /runs/detect-type` returns.

    ``verdict`` is part of the answer rather than a detail: a wrong silent assignment
    is worse than a question, so "I am not sure" has to be representable.
    """

    verdict: str
    reason: str = ""
    key: Optional[str] = None
    label: Optional[str] = None
    score: float = 0.0
    candidates: list[DetectedCandidate] = Field(default_factory=list)
    sheets: list[DetectedSheet] = Field(default_factory=list)
