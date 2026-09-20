"""Wire models for the admin API (Phase 4).

Separate from `schemas.py` because the admin surface is a different audience with a
different shape: it edits configuration, where the run surface reads results.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from greenlight_ai import scopes
from greenlight_ai.api.schemas import ScopeToken
from greenlight_ai.checks.guides import GuideEntry

__all__ = [
    "ArtifactTypeIn",
    "ArtifactTypeOut",
    "ScopeIn",
    "ScopeOut",
    "TemplateOut",
    "NamedValueIn",
    "NamedValueOut",
    "BuiltInExample",
    "CorrectionOut",
    "CheckIn",
    "CheckOut",
    "ExampleFieldOut",
    "ExampleIn",
    "ExampleOut",
    "ExamplePatch",
    "ExampleStageOut",
    "PromoteIn",
    "DraftRequest",
    "DraftResponse",
    "TestRequest",
    "TestResult",
    "ComplianceRuleIn",
    "ComplianceRuleOut",
    "CategoryIn",
    "CategoryOut",
    "AliasIn",
    "AliasOut",
    "MaskedColumnIn",
    "MaskedColumnOut",
    "UsageOut",
]

Severity = Literal["high", "medium", "low", "review"]
LocatorKind = Literal["cell", "label", "config"]


class ArtifactTypeIn(BaseModel):
    """An input the tool accepts, as the admin-ui submits it (ADR-020)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["osl", "config", "report"] = "report"
    description: str = ""
    #: What the model should pay attention to, in plain language. Empty means the
    #: prompts are exactly what they were before this existed.
    ai_context: str = ""
    is_active: bool = True
    is_required: bool = False
    sort_order: int = 100


class SampleOut(BaseModel):
    """One uploaded example of an artifact type (ADR-021)."""

    id: int
    label: str = ""
    #: The programme this sample belongs to; "" for a global one (Phase 6.10).
    scope_code: str = ""
    filename: str = ""
    sheets: list[str] = Field(default_factory=list)
    size_bytes: int = 0
    notes: str = ""
    uploaded_by: str = ""
    created_at: dt.datetime


class SamplePreviewOut(BaseModel):
    """What a sample workbook actually contains, for someone deciding what it means.

    Values pass through the same masking as a real upload, because a sample is a file
    that may hold customer data (ADR-003).
    """

    sample_id: int
    filename: str = ""
    sheets: list["SheetPreview"] = Field(default_factory=list)


class SheetPreview(BaseModel):
    """One sheet of a sample: its labels, its cells, and its values."""

    name: str
    rows: int = 0
    columns: int = 0
    #: Up to a few hundred populated cells: the address, the label to its left when
    #: there is one, and the value as shown.
    cells: list["CellPreview"] = Field(default_factory=list)


class CellPreview(BaseModel):
    """One populated cell, addressable the way a named value addresses it."""

    cell: str
    value: str = ""
    label: str = ""
    row: int = 0
    column: int = 0


class ArtifactTypeOut(ArtifactTypeIn):
    """A stored artifact type, with what is known about its sample."""

    id: int
    is_builtin: bool = False
    #: Up to three, so variation between customers is visible rather than averaged
    #: into whichever workbook was uploaded first (ADR-021).
    samples: list[SampleOut] = Field(default_factory=list)
    #: Every sheet name across all samples, which is what a named value's sheet
    #: dropdown offers.
    sheets: list[str] = Field(default_factory=list)
    #: How many runs have uploaded this type. A type in use cannot be deleted.
    runs_using: int = 0
    #: The validation guide (Phase 6.8b), with examples filled from the samples.
    guide: list[GuideEntry] = Field(default_factory=list)
    #: The newest definition version (ADR-029); zero before the first save.
    version: int = 0


class ScopeIn(BaseModel):
    """A delivery programme, as the admin-ui submits it."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=2, max_length=20)
    label: str = Field(min_length=1, max_length=120)
    description: str = ""
    #: Compliance expectations true of every run in this programme. Passed to the
    #: model as background, never as an OSL requirement.
    standing_instructions: str = ""
    is_active: bool = True
    sort_order: int = 100
    #: Whether a run in this programme needs a second person to approve before it can
    #: be frozen, when the reviewer waved through something this programme treats as
    #: serious. Off by default, and meaningless with login off (ADR-036).
    second_approver: bool = False
    #: Words that mark a delivery as this programme's; the classification check
    #: scans the inputs for them (ADR-026).
    keywords: list[str] = Field(default_factory=list)


class ScopeOut(ScopeIn):
    """A stored delivery programme."""

    id: int
    runs_using: int = 0
    #: The newest version of its rule set (ADR-029); zero before the first save.
    version: int = 0


class TemplateOut(BaseModel):
    """A sample workbook uploaded for one report type."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    report_type: str
    filename: str
    notes: str = ""
    created_at: dt.datetime
    sheets: list[str] = Field(default_factory=list)


class NamedValueIn(BaseModel):
    """A pointer into a report, as the admin-ui submits it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    report_type: str = Field(min_length=1)
    sheet: str = ""
    kind: LocatorKind = "label"
    cell: str = ""
    label: str = ""
    label_column: int = 0
    value_column: int = 1
    description: str = ""


class NamedValueOut(NamedValueIn):
    """A stored pointer, with the value it resolves to on the sample workbook."""

    id: int
    resolved: Optional[str] = None
    used_by: list[str] = Field(default_factory=list)


class CheckIn(BaseModel):
    """A cross-report check, as the admin-ui submits it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    kind: Literal["expression", "judgment"] = "expression"
    expression: str = ""
    instruction: str = ""
    #: For a judgment check: the named values the model may see (ADR-039). Empty for
    #: an expression check, which code evaluates without a model.
    value_names: list[str] = Field(default_factory=list)
    reasoning: str = ""
    severity: Severity = "medium"
    scope: ScopeToken = scopes.EVERYWHERE
    is_active: bool = True


class CheckOut(CheckIn):
    """A stored check, with its version."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    created_at: dt.datetime
    references: list[str] = Field(default_factory=list)


class DraftRequest(BaseModel):
    """A plain-English description of a check to be drafted."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=10)
    report_types: list[str] = Field(default_factory=list)


class DraftResponse(BaseModel):
    """What the model proposed. The admin corrects it before testing."""

    named_values: list[NamedValueIn] = Field(default_factory=list)
    expression: str = ""
    reasoning: str = ""
    severity: Severity = "medium"
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)


class TestRequest(BaseModel):
    """An expression to try against the uploaded sample workbooks."""

    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1)


class TestResult(BaseModel):
    """What a check did against the samples. No LLM call is made."""

    passed: Optional[bool] = None
    detail: str = ""
    resolved: dict[str, Any] = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)


class ComplianceRuleIn(BaseModel):
    """A rule that must be present in every config in scope."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    json_path_contains: str = Field(min_length=1)
    expected_value: Any = True
    scope: ScopeToken = scopes.EVERYWHERE
    reasoning: str = ""
    is_active: bool = True


class ComplianceRuleOut(ComplianceRuleIn):
    """A stored compliance rule."""

    id: int
    #: Bumped on every edit, so a finding can say which wording produced it.
    version: int = 1


class CategoryIn(BaseModel):
    """A reverse-pass category and whether it is checked."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    kinds: list[str] = Field(default_factory=list)
    checked: bool = True


class CategoryOut(CategoryIn):
    """A stored category."""

    id: int


class AliasIn(BaseModel):
    """One alias for a canonical attribute name."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str = Field(min_length=1, max_length=200)
    alias: str = Field(min_length=1, max_length=200)
    customer_name: Optional[str] = None


class AliasOut(AliasIn):
    """A stored alias."""

    id: int


class AnnouncementIn(BaseModel):
    """A notice to show at the top of an app for a while (Phase 6.14g)."""

    model_config = ConfigDict(extra="forbid")

    #: ``info`` · ``warning`` · ``critical``.
    level: str = "info"
    #: ``user`` · ``admin`` · ``both``.
    audience: str = "both"
    message: str = Field(min_length=1, max_length=2000)
    #: Both required. A notice with no end is the stale-banner problem this avoids.
    starts_at: dt.datetime
    ends_at: dt.datetime
    is_active: bool = True


class AnnouncementOut(AnnouncementIn):
    """A stored notice."""

    id: int
    created_by: str = ""
    #: Whether it is showing at this moment, so the console can say so rather than
    #: leaving an administrator to compare dates in their head.
    showing_now: bool = False


class FieldLabelIn(BaseModel):
    """What a delivery calls one of the fields the tool checks (Phase 6.14b).

    Document labels, not data attribute names: the credit date is written *as-of
    date* on one customer's reports and *cycle date* on another's. Scoped with the
    one scope vocabulary (ADR-029), so a programme or a single configuration can
    name its own spelling without changing anybody else's.
    """

    model_config = ConfigDict(extra="forbid")

    #: Which field this names. A closed set; unknown values are refused.
    canonical: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=200)
    #: ``everywhere``, ``programme:CODE``, ``customer:NAME`` or ``config:ID``.
    scope: str = "everywhere"
    is_active: bool = True


class FieldLabelOut(FieldLabelIn):
    """A stored label."""

    id: int
    #: The scope written the way the screens write it, e.g. "Account Monitoring".
    scope_label: str = ""
    created_by: str = ""
    #: True for the spellings that ship with the tool. They cannot be edited or
    #: deleted; a delivery that says it differently adds its own.
    is_builtin: bool = False


class MaskedColumnIn(BaseModel):
    """A report column pattern whose values are masked at parse time."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=200)
    description: str = ""


class MaskedColumnOut(MaskedColumnIn):
    """A stored masked-column pattern."""

    id: int
    is_default: bool = False


class DayCount(BaseModel):
    """One day's total, for the usage sparklines."""

    day: str
    count: int


class UsageOut(BaseModel):
    """The admin dashboard numbers, all plain SQL over the run tables."""

    runs_total: int = 0
    runs_per_day: list[DayCount] = Field(default_factory=list)
    duration_p50_ms: int = 0
    duration_p95_ms: int = 0
    failure_rate: float = 0.0
    tokens_total: int = 0
    tokens_per_day: list[DayCount] = Field(default_factory=list)
    cache_hit_rate: float = 0.0
    json_failure_rate: float = 0.0
    false_positive_rate: float = 0.0
    findings_by_type: dict[str, int] = Field(default_factory=dict)
    decisions: dict[str, int] = Field(default_factory=dict)


class ProgrammeRuleIn(BaseModel):
    """A rule true of every delivery in a programme (ADR-026)."""

    model_config = ConfigDict(extra="forbid")

    scope_code: str = Field(min_length=2, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=3, max_length=4000)
    #: must (a breach is high), should (medium), advisory (low).
    strictness: Literal["must", "should", "advisory"] = "should"
    sort_order: int = 100


class ProgrammeRuleOut(ProgrammeRuleIn):
    """A stored programme rule."""

    id: int
    state: str = "active"
    origin: str = "admin"
    created_by: str = ""


class VersionOut(BaseModel):
    """One retained version of a definition (ADR-029)."""

    version: int
    summary: str = ""
    reverted_from: int | None = None
    created_by: str = ""
    created_at: dt.datetime
    snapshot: dict[str, Any] = Field(default_factory=dict)


class RevertIn(BaseModel):
    """The typed confirmation for a revert."""

    model_config = ConfigDict(extra="forbid")

    confirm: str = ""


class GuideIn(BaseModel):
    """A validation guide, as the admin-ui submits it (Phase 6.8b)."""

    model_config = ConfigDict(extra="forbid")

    entries: list[GuideEntry] = Field(default_factory=list)


class BulkDeleteIn(BaseModel):
    """Several ids and the typed word (ADR-032)."""

    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1, max_length=500)
    confirm: str = ""


class BulkResult(BaseModel):
    """What a bulk action did."""

    deleted: int = 0
    missing: list[int] = Field(default_factory=list)


class SamplePatch(BaseModel):
    """An edit to a stored sample: its label, its notes, or which programme it belongs to."""

    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = None
    notes: Optional[str] = None
    scope_code: Optional[str] = None


class ExampleIn(BaseModel):
    """A worked example an administrator gives the model (Phase 6.13d, ADR-038)."""

    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=40)
    scope: ScopeToken = scopes.EVERYWHERE
    #: What the model would be shown, keyed by the stage's field names.
    given: dict[str, str] = Field(default_factory=dict)
    #: A good answer. Validated against the stage's own schema before it is stored.
    answer: dict[str, Any] = Field(default_factory=dict)
    #: Why it is here. For the next administrator; never rendered into a prompt.
    note: str = ""
    is_active: bool = True
    sort_order: int = 0


class ExamplePatch(BaseModel):
    """An edit to a stored example; every field is optional."""

    model_config = ConfigDict(extra="forbid")

    scope: Optional[ScopeToken] = None
    given: Optional[dict[str, str]] = None
    answer: Optional[dict[str, Any]] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class ExampleOut(ExampleIn):
    """A stored example, with where it came from and who wrote it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    #: ``admin``, or ``promoted:<kind>:<id>`` when a person promoted a decision.
    origin: str = "admin"
    created_by: str = ""
    created_at: dt.datetime
    updated_by: str = ""
    updated_at: dt.datetime


class ExampleFieldOut(BaseModel):
    """One part of what a stage shows the model."""

    name: str
    label: str
    shape: str


class BuiltInExample(BaseModel):
    """An example that ships in the prompt, shown read-only above the library."""

    number: int
    shown: str
    answer: str


class ExampleStageOut(BaseModel):
    """One stage an administrator may add examples to."""

    stage: str
    label: str
    description: str
    fields: list[ExampleFieldOut] = Field(default_factory=list)
    built_in: list[BuiltInExample] = Field(default_factory=list)
    #: How many library examples this stage may carry.
    max_examples: int = 4


class CorrectionOut(BaseModel):
    """A requirement a reviewer rewrote, offered as an extraction example (ADR-038).

    A correction is the model being told it read a section wrongly, which is exactly
    what a worked example is for. It is shown here so an administrator can decide to
    teach it; nothing is promoted without their click.
    """

    run_id: int
    rule_id: str
    customer: str = ""
    #: The wording the requirement quotes, which is what the model would be shown.
    source_text: str = ""
    summary: str = ""
    edited_by: str = ""
    edited_at: Optional[dt.datetime] = None
    #: Whether this correction has already been promoted.
    promoted: bool = False


class PromoteIn(BaseModel):
    """Turn a decision a person already confirmed into a worked example (ADR-038).

    Nothing is promoted without this call, which a person makes by clicking.
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["meaning", "requirement", "candidate"]
    #: The meaning entry, the candidate, or the run whose requirement was corrected.
    id: int
    #: For a corrected requirement: which one, e.g. ``"R-003"``.
    rule_id: str = ""
    scope: ScopeToken = scopes.EVERYWHERE
    note: str = ""
