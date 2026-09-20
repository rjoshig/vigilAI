"""Wire models for the API.

Pydantic at the boundary only (standards/python.md). These are deliberately separate
from the canonical rule schema: the wire format can gain a field for the UI without
changing what the pipeline compares.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from greenlight_ai import scopes

__all__ = [
    "ScopeToken",
    "NewRunOptions",
    "ArtifactSlot",
    "ScopeOption",
    "RunSummary",
    "RunDetail",
    "StageInfo",
    "FindingOut",
    "RunRuleOut",
    "RunRulesOut",
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


def _canonical_scope(value: object) -> object:
    """Read any stored or submitted scope form and hand back the canonical token.

    The wire is where the vocabulary is unified (ADR-037): an older form still arrives
    and is understood, and what goes back out is always the one token, so a console
    never has to know that four shapes were ever stored.

    Args:
        value: Whatever arrived on the wire.

    Returns:
        The canonical token for a string, and the value untouched for anything else,
        so pydantic reports the type error rather than this function hiding it.
    """
    return scopes.token(value) if isinstance(value, str) else value


#: A scope on the wire: any form in, the canonical token out.
ScopeToken = Annotated[str, BeforeValidator(_canonical_scope)]


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
    #: The credit date the delivery is cut as of, shown with the configuration id so a
    #: repeated configuration reads as "which month" (ADR-027).
    credit_date: Optional[dt.date] = None


class RunDetail(RunSummary):
    """A run with everything the Review screen needs up front."""

    notes: str = ""
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
    #: Why not, when ``can_finalize`` is false: one sentence naming what is
    #: outstanding (Phase 6.11d). Empty when the gate is satisfied.
    finalize_blocked_by: str = ""
    finalized: bool = False
    #: Whether this deployment can render a PDF at all. False when the optional [pdf]
    #: extra is not installed, which is a deployment fact, not a per-run one.
    pdf_available: bool = False
    stages: list[StageInfo] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    #: Where the artifacts disagreed with what was submitted, accepted or not
    #: (ADR-041). Shown above the findings, because a mismatch says the findings may
    #: have been computed against the wrong premise.
    mismatches: list["ArtifactMismatchOut"] = Field(default_factory=list)


class RequirementCoverageOut(BaseModel):
    """How far one requirement got (Phase 6.11c)."""

    rule_id: str
    req_type: str = ""
    state: str
    osl_ref: str = ""
    summary: str = ""
    reason: str = ""
    #: Whether a person has recorded that they saw this gap.
    acknowledged: bool = False
    acknowledged_by: str = ""
    acknowledgement_note: str = ""


class ReportCoverageOut(BaseModel):
    """How many checks touched one uploaded report."""

    kind: str
    checks_applied: int = 0


class UnevaluatedCheckOut(BaseModel):
    """A check that was defined and could not be run."""

    finding_id: str
    title: str = ""
    acknowledged: bool = False
    acknowledged_by: str = ""
    acknowledgement_note: str = ""


class CoverageOut(BaseModel):
    """What the run checked and what it did not."""

    requirements: list[RequirementCoverageOut] = Field(default_factory=list)
    reports: list[ReportCoverageOut] = Field(default_factory=list)
    unevaluated: list[UnevaluatedCheckOut] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    #: Requirement ids and finding ids still waiting for an acknowledgement.
    outstanding: list[str] = Field(default_factory=list)
    #: Empty for a run processed before coverage existed, which the screen says
    #: rather than showing an empty panel.
    reason: str = ""


class SecondApprovalPayload(BaseModel):
    """A second person signing off what the first waved through (ADR-036)."""

    model_config = ConfigDict(extra="forbid")

    note: str = ""


class SecondApprovalOut(BaseModel):
    """What the four-eyes rule is waiting on, and who has signed."""

    #: Whether this run's programme asks for a second approver at all.
    required: bool = False
    #: Serious findings the reviewer marked OK. Empty when nothing was waved through.
    findings: list[str] = Field(default_factory=list)
    #: Whether the signature that is needed is still outstanding.
    outstanding: bool = False
    approved_by: str = ""
    approved_at: Optional[dt.datetime] = None
    note: str = ""


class AcknowledgePayload(BaseModel):
    """Recording that a person has seen a gap."""

    model_config = ConfigDict(extra="forbid")

    targets: list[str] = Field(min_length=1)
    note: str = ""


class ExploreSampleOut(BaseModel):
    """One sample a reviewer can look at (Phase 6.1e).

    Deliberately smaller than the admin console's view: a reviewer is choosing
    something to point at, not maintaining the catalog.
    """

    id: int
    label: str = ""
    filename: str = ""
    sheets: list[str] = Field(default_factory=list)
    notes: str = ""
    #: The programme it belongs to; empty for a global sample.
    scope_code: str = ""


class ExploreArtifactOut(BaseModel):
    """An artifact type and the samples stored for it."""

    key: str
    label: str = ""
    #: ``osl``, ``config`` or a report kind. It decides what a preview looks like:
    #: sections, JSON paths, or cells.
    kind: str = ""
    samples: list[ExploreSampleOut] = Field(default_factory=list)


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
    #: What each of stage 8's lenses said (Phase 6.11e). Empty for a run verified by
    #: the single second opinion.
    lens_opinions: list[dict[str, Any]] = Field(default_factory=list)
    #: Where the finding came from (Phase 6.13b): ``built_in`` when code produced it
    #: from the OSL and the configuration alone, else the origin of the rule behind it —
    #: ``admin`` · ``guide`` · ``meaning`` · ``learned``. A reviewer deserves to know
    #: that a finding exists because a colleague wrote a sentence.
    origin: str = "built_in"
    rule_name: str = ""
    rule_summary: str = ""
    run_id: int = 0


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
    #: How many findings each path produced (Phase 6.16). Code is the overwhelming
    #: majority and should stay that way: a run where the model produced most of
    #: the findings is a run worth looking at.
    findings_by_engine: dict[str, int] = Field(default_factory=dict)
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


class ArtifactMismatchOut(BaseModel):
    """One field where the artifacts disagree with what was submitted (ADR-041)."""

    id: int
    field: str
    #: A short label for the field, so the screen does not have to know the vocabulary.
    label: str = ""
    submitted: str = ""
    declared: str = ""
    #: ``near`` (the same once punctuation and company suffixes are removed) or
    #: ``different``.
    kind: str = "different"
    source: str = ""
    reason: str = ""
    accepted_at: Optional[dt.datetime] = None
    accepted_by: str = ""

    model_config = ConfigDict(from_attributes=True)


class AcceptMismatches(BaseModel):
    """Accept the disagreements on a held run and let it start.

    One reason covers every mismatch, because the person is answering one question —
    "yes, these artifacts are the delivery I meant" — and asking it once per field
    would train them to type the same words three times.
    """

    reason: str = Field(min_length=1, max_length=2000)
    #: Which fields to accept. Empty means all of them, which is what the button does.
    fields: list[str] = Field(default_factory=list)


class AcceptMismatchesResult(BaseModel):
    """What `POST /runs/{id}/match/accept` returns."""

    run_id: int
    status: str
    accepted: int
    queue_position: Optional[int] = None


class CreateRunResult(BaseModel):
    """What `POST /runs` returns."""

    run_id: Optional[int] = None
    status: str = ""
    queue_position: Optional[int] = None
    duplicate: Optional[DuplicateRun] = None
    #: Present and non-empty when the run is ``held``: the artifacts disagree with what
    #: was typed and somebody has to accept before it starts (ADR-041). The files are
    #: stored and nothing needs re-uploading.
    mismatches: list[ArtifactMismatchOut] = Field(default_factory=list)


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


class DriftFinding(BaseModel):
    """A finding as the drift panel refers to it (ADR-030)."""

    finding_id: str
    type: str
    severity: str
    title: str
    review_status: str = "undecided"


class DriftRequirement(BaseModel):
    """A requirement that appeared, vanished, or changed value since last time."""

    rule_id: str
    req_type: str
    source_ref: str
    change: Literal["added", "removed", "changed"]
    before: str = ""
    after: str = ""


class DriftConfigChange(BaseModel):
    """One configuration path that differs from the previous run's."""

    path: str
    change: Literal["added", "removed", "changed"]
    before: str = ""
    after: str = ""


class DriftOut(BaseModel):
    """What changed since the previous finalized run of the same configuration."""

    previous_run_id: Optional[int] = None
    previous_finished_at: str = ""
    previous_verdict: str = ""
    reason: str = ""
    new: list[DriftFinding] = Field(default_factory=list)
    resolved: list[DriftFinding] = Field(default_factory=list)
    carried_not_ok: list[DriftFinding] = Field(default_factory=list)
    requirements: list[DriftRequirement] = Field(default_factory=list)
    config: list[DriftConfigChange] = Field(default_factory=list)
    previous_config_version: Optional[int] = None
    config_version: Optional[int] = None
    #: OSL references a report evidenced last time and evidences no longer.
    newly_unchecked: list[str] = Field(default_factory=list)


class RunRuleOut(BaseModel):
    """One rule that touched a run (Phase 6.13b)."""

    rule_ref: str
    kind: str
    name: str
    summary: str = ""
    origin: str = "admin"
    state: str = "active"
    #: How many findings it produced on this run. Zero for a shadow rule, whose
    #: findings are counted for the administrator and shown to nobody (ADR-021).
    findings: int = 0
    shadow: bool = False


class RunRulesOut(BaseModel):
    """The rules applied to a run, as a reviewer may see them."""

    applied: list[RunRuleOut] = Field(default_factory=list)
    #: Rules that ran in shadow on this run, named and nothing more.
    running_silently: list[RunRuleOut] = Field(default_factory=list)
