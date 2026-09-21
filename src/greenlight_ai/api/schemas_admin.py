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
    "AliasCopyPreview",
    "AttributeAcceptIn",
    "AttributeSuggestionOut",
    "AttributeSuggestionsOut",
    "AttributeSpellingIn",
    "AttributeTermIn",
    "AttributeTermOut",
    "ProductCodeIn",
    "ProductCodeMemberIn",
    "ProductCodeOut",
    "UsageOut",
]

Severity = Literal["high", "medium", "low", "review"]
LocatorKind = Literal["cell", "label", "config"]


class ArtifactTypeIn(BaseModel):
    """An input the tool accepts, as the admin-ui submits it (ADR-020)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    #: A record layout is a fourth kind (Phase 6.22b). Only reports may be added or
    #: removed; the other three are built in and their keys are fixed, because the
    #: pipeline reads each with a dedicated parser.
    kind: Literal["osl", "config", "record_layout", "report"] = "report"
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
    #: What this delivery calls each name the fixed checks look for (Phase 6.21b).
    layout: list[LayoutEntryWire] = Field(default_factory=list)
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
    #: Other configuration paths that also count as implementing this rule
    #: (Phase 6.15). Spelling and an extra level of nesting are already allowed for;
    #: this is for the case no amount of normalising reaches — a customer whose OFAC
    #: screening is called ``suppressions.sdn_screening``.
    alternates: list[str] = Field(default_factory=list, max_length=10)
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


class AttributeSpellingIn(BaseModel):
    """One way an artifact writes an attribute (Phase 6.22d)."""

    model_config = ConfigDict(extra="forbid")

    spelling: str = Field(min_length=1, max_length=200)
    #: Which artifact writes it this way, e.g. ``dirt``. Empty means anywhere, which is
    #: the ordinary case and what an administrator writes by hand.
    artifact: str = Field(default="", max_length=60)
    #: admin · record_layout · model · observation · alias. Provenance sits on the
    #: spelling rather than the term, because it is the spelling somebody vouched for.
    origin: str = Field(default="admin", max_length=30)
    origin_run_id: int = 0


class AttributeTermIn(BaseModel):
    """One attribute and every name it goes by, as the admin-ui submits it (6.22d).

    The dictionary the project has carried an open question about since Phase 0. It is
    the ladder's **fourth rung** for attribute names: a lookup for any spelling reaches
    the term, and the term's other spellings become the alternates the ladder is given.
    It never picks — the ladder still refuses to answer when two candidates tie.
    """

    model_config = ConfigDict(extra="forbid")

    canonical: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)
    description: str = ""
    #: ``everywhere``, ``programme:CODE``, ``customer:NAME`` or ``config:ID``.
    scope: str = "everywhere"
    spellings: list[AttributeSpellingIn] = Field(default_factory=list)
    is_active: bool = True


class AttributeTermOut(AttributeTermIn):
    """A stored term."""

    id: int
    scope_label: str = ""
    created_by: str = ""
    spelling_count: int = 0


class AliasCopyPreview(BaseModel):
    """What copying the legacy alias table into the dictionary would do (6.22d).

    Shown before anything is written. The aliases are **read** alongside the dictionary
    whether or not anybody copies them (ADR-062), so this is a tidying step somebody
    chooses rather than a migration that happens behind their back.
    """

    #: Terms that would be created, with the spellings each would gain.
    creates: list[AttributeTermIn] = Field(default_factory=list)
    #: Terms that already exist and would gain spellings.
    extends: list[AttributeTermIn] = Field(default_factory=list)
    #: Aliases already in the dictionary, which would be skipped.
    already_known: int = 0
    #: What was actually written, on a copy. Zero on a preview.
    written: int = 0


class ProductCodeMemberIn(BaseModel):
    """One attribute a product code contains (Phase 6.22c)."""

    model_config = ConfigDict(extra="forbid")

    #: The attribute as the catalogue names it, which is what the OSL is expected to
    #: say and what the checks ask for.
    attribute: str = Field(min_length=1, max_length=200)
    #: What the delivered file calls it, when that differs. Empty means it is
    #: delivered under its own name, which is the ordinary case.
    output_name: str = Field(default="", max_length=200)


class ProductCodeIn(BaseModel):
    """A product code, as the admin-ui submits it (Phase 6.22c).

    An OSL says either *"deliver AT01, AT02, ST"* or *"deliver all attributes from
    ABC"*, and this is what makes the second mean the first. The model reads that a
    requirement names a code; **code** looks up what the code contains and checks that
    it exists at all (ADR-061).

    Scoped with the one scope vocabulary (ADR-029, ADR-037), because one customer's
    ``ABC`` is not another's.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=60)
    label: str = Field(default="", max_length=200)
    description: str = ""
    #: ``everywhere``, ``programme:CODE``, ``customer:NAME`` or ``config:ID``.
    scope: str = "everywhere"
    members: list[ProductCodeMemberIn] = Field(default_factory=list)
    is_active: bool = True
    sort_order: int = 100
    notes: str = ""


class ProductCodeOut(ProductCodeIn):
    """A stored product code."""

    id: int
    scope_label: str = ""
    created_by: str = ""
    #: How many attributes it contains, so a list does not have to count them.
    member_count: int = 0
    #: Attributes this code shares with another under a **different** delivered name.
    #: A shared attribute is one term with one output name, so a disagreement is a
    #: defect in the catalogue rather than two opinions to choose between; naming it is
    #: what lets an administrator fix it.
    conflicts: list[str] = Field(default_factory=list)


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


class ValueReportOut(BaseModel):
    """What the tool displaced over a chosen period (Phase 6.16)."""

    start: dt.date
    end: dt.date
    days: int = 0
    runs: int = 0
    #: Distinct order numbers, which is what the hours are based on. An order checked
    #: three times displaced one manual check, not three.
    orders: int = 0
    customers: int = 0
    repeat_runs: int = 0
    #: The figure an administrator supplied; carried so a reader can disagree with the
    #: assumption rather than with the arithmetic.
    hours_per_order: int = 0
    hours_saved: int = 0
    working_weeks: float = 0.0


class UserUsageOut(BaseModel):
    """One person's use of the tool over a period (Phase 6.19)."""

    user_id: int
    #: Their name, or their username where they have none.
    name: str = ""
    username: str = ""
    #: Every role they hold, weakest first (ADR-049).
    roles: list[str] = Field(default_factory=list)
    #: Deactivated accounts still appear: what they did does not stop having happened.
    is_active: bool = True

    runs: int = 0
    finalized: int = 0
    needs_review: int = 0
    failed: int = 0
    #: The artifacts disagreed with the form and nobody has accepted it (ADR-041).
    held: int = 0
    cancelled: int = 0
    #: Queued or running when the report was built.
    in_flight: int = 0

    #: Distinct order numbers: how much work, rather than how many attempts.
    orders: int = 0
    customers: int = 0
    configurations: int = 0
    repeat_runs: int = 0
    #: Runs that recorded an artifact disagreement, accepted or not.
    mismatch_runs: int = 0
    #: Tokens their runs actually sent, and what those cost at the configured rate
    #: (Phase 6.21d). Zero cost means no rate is set, not that they spent nothing.
    tokens: int = 0
    cost: float = 0.0
    cached_calls: int = 0
    high_findings: int = 0
    completed_runs: int = 0

    #: The three ways a run goes wrong, as rates, to compare against the deployment's
    #: own averages on `UsageByUserOut` rather than against an invented threshold.
    failure_rate: float = 0.0
    held_rate: float = 0.0
    repeat_rate: float = 0.0
    high_per_run: float = 0.0

    first_run_at: Optional[dt.datetime] = None
    last_run_at: Optional[dt.datetime] = None
    #: Sparse: a day they submitted nothing is absent rather than zero.
    per_day: list[DayCount] = Field(default_factory=list)


class UsageByUserOut(BaseModel):
    """Everyone's use of the tool over one period (Phase 6.19)."""

    start: dt.date
    end: dt.date
    days: int = 0
    #: Busiest first.
    users: list[UserUsageOut] = Field(default_factory=list)
    runs: int = 0
    #: The deployment's own averages. A person's rate means something next to these
    #: and nothing on its own.
    failure_rate: float = 0.0
    held_rate: float = 0.0
    repeat_rate: float = 0.0
    #: The periods the console may ask for, so the picker cannot drift from the API.
    periods: list[int] = Field(default_factory=list)
    #: The rate every row's cost was computed at, carried once rather than on each row
    #: (Phase 6.21d). Zero means no rate is set and the console shows tokens only.
    rate_per_million: float = 0.0
    currency: str = "USD"


class SpendOut(BaseModel):
    """What some period or some runs cost (Phase 6.21d)."""

    #: Whole currency units per million tokens, as configured. Zero means no rate has
    #: been set and every other money figure here is zero and should not be shown.
    rate_per_million: float = 0.0
    currency: str = "USD"
    #: Tokens actually sent, across calls the cache did not serve.
    tokens: int = 0
    #: Those tokens at the rate.
    cost: float = 0.0
    #: This calendar month's spend, and the band an administrator set. A band produces
    #: a warning and never a refusal: the per-run token budget stays the only hard stop.
    month_cost: float = 0.0
    month_tokens: int = 0
    monthly_warning: float = 0.0
    #: Calls the cache served. They cost nothing and are counted apart rather than
    #: folded in, where they would flatter the total.
    cached_calls: int = 0
    calls: int = 0
    #: One entry per day that made a call, oldest first, so a strip can be drawn.
    per_day: list[DayCost] = Field(default_factory=list)

    @property
    def known(self) -> bool:
        """Whether a cost can be shown at all."""
        return self.rate_per_million > 0


class DayCost(BaseModel):
    """One day's tokens and cost."""

    day: str
    tokens: int = 0
    cost: float = 0.0


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
    #: What it all cost (Phase 6.21d). Zero throughout when nobody has set a rate, in
    #: which case the console shows tokens and no currency at all — a cost built on a
    #: rate nobody supplied is a number that gets quoted back as fact.
    spend: SpendOut = Field(default_factory=lambda: SpendOut())
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


class LayoutEntryWire(BaseModel):
    """One name a delivery spells differently (Phase 6.21b)."""

    model_config = ConfigDict(extra="forbid")

    #: Which runs it covers, in the one scope vocabulary (ADR-037). Empty is
    #: everywhere.
    scope: str = ""
    #: ``sheet``, ``column`` or ``label``.
    kind: str = "sheet"
    #: The name the fixed checks ask for, e.g. ``Attributes``.
    wanted: str = Field(min_length=1, max_length=120)
    #: What this delivery calls it. Several, because one type can be delivered by
    #: customers who each word it differently.
    names: list[str] = Field(default_factory=list)
    note: str = ""
    added_by: str = ""


class LayoutIn(BaseModel):
    """A layout map, as the admin-ui submits it."""

    model_config = ConfigDict(extra="forbid")

    entries: list[LayoutEntryWire] = Field(default_factory=list)


class LayoutSuggestionOut(BaseModel):
    """A name the model read for a run, offered to an administrator (ADR-054)."""

    artifact: str = ""
    kind: str = "sheet"
    wanted: str = ""
    found: str = ""
    #: The model's own number, already past the floor code applies.
    confidence: float = 0.0
    reason: str = ""
    #: How many runs met it. A name read on every delivery from a customer is that
    #: customer's layout; one read once may be a one-off workbook.
    seen: int = 0
    #: The runs it came from, so the delivery can be read before the name is recorded.
    run_ids: list[int] = Field(default_factory=list)
    #: True when the artifact type already carries it, so an accepted suggestion
    #: stops asking to be accepted.
    already_listed: bool = False


class LayoutSuggestionsOut(BaseModel):
    """Every pending layout suggestion."""

    suggestions: list[LayoutSuggestionOut] = Field(default_factory=list)


class LayoutAcceptIn(BaseModel):
    """Record one read name on its artifact type."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(min_length=1)
    kind: str = "sheet"
    wanted: str = Field(min_length=1)
    found: str = Field(min_length=1)
    #: Which runs it should apply to. Empty is everywhere, which is the right default
    #: for a report type only one customer delivers and the wrong one otherwise — so
    #: the console offers the run's programme first.
    scope: str = ""


class AttributeSuggestionOut(BaseModel):
    """What a delivery appears to call one attribute, offered to a person (6.22f)."""

    artifact: str = ""
    wanted: str = ""
    found: str = ""
    #: ``record_layout`` for a mapping code read out of the delivered file's own
    #: schema, at no model call; ``model`` for one the ladder's fifth rung reached.
    origin: str = "model"
    #: The model's own number for a reading; ``1.0`` for a record layout, which is a
    #: claim about provenance rather than certainty — a person still decides.
    confidence: float = 0.0
    reason: str = ""
    #: How many runs met it. A mapping seen on every delivery from a customer is that
    #: customer's vocabulary; one seen once may be a one-off workbook.
    seen: int = 0
    run_ids: list[int] = Field(default_factory=list)
    #: True when the dictionary already holds it, so an accepted mapping stops asking
    #: to be accepted.
    already_listed: bool = False


class AttributeSuggestionsOut(BaseModel):
    """Every pending attribute mapping."""

    suggestions: list[AttributeSuggestionOut] = Field(default_factory=list)


class AttributeAcceptIn(BaseModel):
    """Record one mapping in the attribute dictionary."""

    model_config = ConfigDict(extra="forbid")

    wanted: str = Field(min_length=1, max_length=200)
    found: str = Field(min_length=1, max_length=200)
    #: Which artifact writes it this way. **Empty by default, meaning anywhere**, and
    #: that default is deliberate: a suggestion carries the artifact it was *seen* in,
    #: but a customer who calls a field ``debsc_burs_atyrt_at01_1`` in their DIRT calls
    #: it that in their record layout and their field distribution too. Narrowing it to
    #: the one artifact it was seen in would leave every other check still asking the
    #: model the question a person has just answered. A console offers the narrowing;
    #: it does not impose it.
    artifact: str = Field(default="", max_length=60)
    #: ``everywhere``, ``programme:CODE``, ``customer:NAME`` or ``config:ID``.
    scope: str = "everywhere"
    #: Where the mapping came from, carried onto the spelling as its provenance.
    origin: str = Field(default="model", max_length=30)
    #: The run it was learned from, so the spelling can be traced back to a delivery.
    origin_run_id: int = 0

    def spelling_key(self) -> str:
        """The name being claimed, for the one-name-one-attribute check.

        Returns:
            The delivery's spelling, which is what another term must not already hold.
        """
        return self.found


class ArtifactReadingOut(BaseModel):
    """What the tool made of one artifact type's samples (Phase 6.21f)."""

    key: str = ""
    label: str = ""
    sample_count: int = 0
    sheets: list[str] = Field(default_factory=list)
    #: The names the fixed checks look for that code found, as wanted → what it is here.
    resolved: dict[str, str] = Field(default_factory=dict)
    #: Names it looked for and code could not settle. Not an error: most do not apply
    #: to most report types, which the screen says rather than listing them as faults.
    unresolved: list[str] = Field(default_factory=list)
    error: str = ""


class NamedValueReadingOut(BaseModel):
    """One pointer, resolved against the samples."""

    name: str = ""
    description: str = ""
    found: bool = False
    value: str = ""


class CheckReadingOut(BaseModel):
    """One check, evaluated over the samples."""

    name: str = ""
    expression: str = ""
    #: ``null`` when a value it needs was not found, which on a real run is a "could
    #: not evaluate" finding rather than a silent skip.
    passed: Optional[bool] = None
    detail: str = ""
    shadow: bool = False


class RehearsalOut(BaseModel):
    """What a setup would do, as far as the samples can say (Phase 6.21f)."""

    scope: str = ""
    artifacts: list[ArtifactReadingOut] = Field(default_factory=list)
    named_values: list[NamedValueReadingOut] = Field(default_factory=list)
    checks: list[CheckReadingOut] = Field(default_factory=list)
    #: What the rehearsal could not tell anybody, said plainly rather than implied by
    #: an empty list.
    notes: list[str] = Field(default_factory=list)


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


class SignatureStateOut(BaseModel):
    """One recurring finding and what people have decided about it (Phase 6.18a)."""

    signature: str
    customer_name: str = ""
    #: The delivery programme's code. Trust is learned per customer per programme, so
    #: what Account Solicitation taught never applies to that customer's Archives work.
    scope: str = ""
    rule_ref: str = ""
    finding_type: str = ""
    #: What it fired on. A blank score column and a blank state column are two
    #: signatures however much they share a rule.
    element_ref: str = ""
    #: watching · would_demote · blocked
    state: str = "watching"
    #: One sentence saying why it is in that state.
    reason: str = ""
    occurrences: int = 0
    dismissed: int = 0
    upheld: int = 0
    severities: list[str] = Field(default_factory=list)
    #: The runs whose verdicts this rests on. A demotion has to be checkable against
    #: the deliveries it was learned from, not merely asserted.
    justified_by_run_ids: list[int] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DemotionReportOut(BaseModel):
    """What demotion would do, before anything acts on it (Phase 6.18a, ADR-043).

    Every reviewer still sees every finding. This is the evidence for the question
    that decides whether they should: *it would have hidden these — was any of them
    real?*
    """

    #: How many signatures are in each state.
    counts: dict[str, int] = Field(default_factory=dict)
    #: The signatures that have earned their way out of the queue, most recent first.
    would_demote: list[SignatureStateOut] = Field(default_factory=list)
    #: Signatures a person has upheld, which are never demotable until cleared.
    blocked: list[SignatureStateOut] = Field(default_factory=list)
    #: True while nothing acts on any of this, which is the whole of 6.18a.
    shadow: bool = True


class KeywordSuggestionOut(BaseModel):
    """A word the model quoted that would have matched a programme (Phase 6.18f)."""

    scope_code: str = ""
    phrase: str = ""
    #: How many deliveries the model quoted it from. A phrase seen repeatedly is the
    #: customer's vocabulary; one seen once may be a turn of phrase.
    seen: int = 0
    #: The runs it came from, so an administrator can read the delivery before
    #: accepting a word into the list that decides what the tool believes.
    run_ids: list[int] = Field(default_factory=list)
    #: True when the programme already lists it, matching how the check compares.
    already_listed: bool = False


class KeywordSuggestionsOut(BaseModel):
    """Every pending suggestion, grouped by programme."""

    suggestions: list[KeywordSuggestionOut] = Field(default_factory=list)


class AcceptKeywordIn(BaseModel):
    """Add one suggested word to a programme's list."""

    scope_code: str = Field(min_length=1)
    phrase: str = Field(min_length=1)


class PromptBudgetOut(BaseModel):
    """What one prompt's context allowance has left (Phase 6.17b)."""

    per_field_cap: int = 0
    block_cap: int = 0
    #: What the configured context takes today, counted the way the trimmer counts it.
    used: int = 0
    remaining: int = 0
    lines: int = 0
    #: True when the block is already over and losing its oldest lines. A field should
    #: say so rather than let somebody write an eleventh note that never arrives.
    trimmed: bool = False
