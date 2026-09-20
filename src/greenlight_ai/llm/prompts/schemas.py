"""Pydantic schemas for LLM output.

These sit on the boundary: a model answer that does not validate is retried once and
then fails loudly rather than flowing downstream (standards/python.md). They are
deliberately narrower than the canonical rule schema, because a stage asks for exactly
what it needs and the pipeline builds the canonical object from the answer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from greenlight_ai.rules.schema import Confidence, Mode, Operator, ReqType, Severity, TraceVerdict

__all__ = [
    "DraftedNamedValue",
    "DraftCheckResponse",
    "JudgmentResponse",
    "ExtractedCondition",
    "ExtractedRequirement",
    "ExtractResponse",
    "DescribedElement",
    "DescribeResponse",
    "TraceResponse",
    "VerifyResponse",
    "LensResponse",
    "MissedItem",
    "SummarizeResponse",
    "CoverageGap",
    "CoverageGapResponse",
    "CritiqueResponse",
    "ClassifyResponse",
]


class ExtractedCondition(BaseModel):
    """One field comparison as the model read it."""

    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(min_length=1)
    operator: Operator
    value: float | int | str | list[float | int | str] | None = None


class ExtractedRequirement(BaseModel):
    """One requirement the model found in an OSL section (stage 2)."""

    model_config = ConfigDict(extra="forbid")

    req_type: ReqType
    conditions: list[ExtractedCondition] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    mode: Mode | None = None
    steps: list[str] = Field(default_factory=list)
    quantity: float | None = None
    action: str = "accept"
    applies_to: str = "all"
    source_text: str = ""
    confidence: Confidence = 0.5


class ExtractResponse(BaseModel):
    """Stage 2's answer for one OSL section or table."""

    model_config = ConfigDict(extra="forbid")

    requirements: list[ExtractedRequirement] = Field(default_factory=list)


class DescribedElement(BaseModel):
    """What one config block does, in requirement vocabulary (stage 3)."""

    model_config = ConfigDict(extra="forbid")

    json_path: str = Field(min_length=1)
    req_type: ReqType | None = None
    is_technical: bool = False
    description: str = ""
    conditions: list[ExtractedCondition] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    mode: Mode | None = None
    steps: list[str] = Field(default_factory=list)
    quantity: float | None = None
    confidence: Confidence = 0.5


class DescribeResponse(BaseModel):
    """Stage 3's answer for one config block."""

    model_config = ConfigDict(extra="forbid")

    elements: list[DescribedElement] = Field(default_factory=list)


class TraceResponse(BaseModel):
    """Stage 4's answer for one (requirement, element) pair."""

    model_config = ConfigDict(extra="forbid")

    verdict: TraceVerdict
    reason: str = ""
    confidence: Confidence = 0.5


class VerifyResponse(BaseModel):
    """Stage 8's second opinion on one high-severity finding."""

    model_config = ConfigDict(extra="forbid")

    agreed: bool
    reason: str = ""
    confidence: Confidence = 0.5


class MissedItem(BaseModel):
    """Something a lens saw in the evidence that the finding does not mention."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    reason: str = ""
    confidence: Confidence = 0.5


class LensResponse(VerifyResponse):
    """One lens's reading of a finding (Phase 6.11e).

    The same answer stage 8 has always wanted, plus at most one thing this lens noticed
    and the finding did not. A proposal is never a graded finding: it becomes a review
    item for a person (ADR-034).
    """

    model_config = ConfigDict(extra="forbid")

    missed: tuple[MissedItem, ...] = ()


class CoverageGap(BaseModel):
    """One unchecked requirement that reads like an obligation (Phase 6.11f)."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = ""
    reason: str = ""
    confidence: Confidence = 0.5


class CoverageGapResponse(BaseModel):
    """Which unchecked requirements look like obligations.

    The model reads the list code produced and points; it decides nothing, and every
    item it returns becomes a review item for a person (ADR-034).
    """

    model_config = ConfigDict(extra="forbid")

    gaps: tuple[CoverageGap, ...] = ()


class CritiqueResponse(BaseModel):
    """Whether a drafted rule says what the statements said (Phase 6.11g).

    It checks the draft, not the data: the model never evaluates a rule, and this
    answer only decides whether one redraft is worth asking for (ADR-001).
    """

    model_config = ConfigDict(extra="forbid")

    faithful: bool = True
    problem: str = ""
    overlaps: bool = False
    overlaps_with: str = ""
    confidence: Confidence = 0.5


class SummarizeResponse(BaseModel):
    """Stage 9's plain-English summary of the findings list."""

    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    top_issues: list[str] = Field(default_factory=list)


class DraftedNamedValue(BaseModel):
    """One pointer the model proposes for a check (admin drafting)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    report_type: str = Field(min_length=1)
    sheet: str = ""
    kind: str = "label"
    label: str = ""
    label_column: int = 0
    value_column: int = 1
    cell: str = ""
    description: str = ""


class DraftCheckResponse(BaseModel):
    """The proposal an administrator corrects before testing and activating."""

    model_config = ConfigDict(extra="forbid")

    named_values: list[DraftedNamedValue] = Field(default_factory=list)
    expression: str = ""
    reasoning: str = ""
    severity: str = "medium"


class JudgmentResponse(BaseModel):
    """A judgment check's answer: the model sees named values and reasoning only."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "fail", "review"]
    reason: str = ""
    confidence: Confidence = 0.5


class ComplianceLocation(BaseModel):
    """Where, if anywhere, a configuration implements a compliance control (6.15A).

    The model answers one narrow question and nothing wider. It is never asked whether
    the delivery is compliant: that is a comparison, and comparisons are code's
    (ADR-001). It is asked where something is, and code decides what that means.
    """

    model_config = ConfigDict(extra="forbid")

    #: ``found`` when a path implements the control, ``absent`` when nothing does,
    #: ``unsure`` when the configuration does not settle it. Prefer ``unsure`` to a
    #: guess: a wrong ``absent`` is a high-severity finding about a control that is
    #: actually in place, and a wrong ``found`` waves through one that is not.
    verdict: Literal["found", "absent", "unsure"]
    #: The configuration path that implements it, when ``found``. Must be a path that
    #: appeared in the input; code checks that it does before believing it.
    json_path: str = ""
    reason: str = ""
    confidence: Confidence = 0.5


class SynthesizedRule(BaseModel):
    """One rule the model proposes from what people wrote (ADR-021).

    The model fills this and nothing else. A schema-constrained object rather than
    prose is the point: loose parsing of free-form model output is where downstream
    code starts trusting something nobody checked, and that is the actual injection
    exposure, not the text the person typed.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    #: Which rule surface this becomes on approval. ``unsupported`` is a real answer:
    #: a statement that cannot be expressed as a rule comes back saying so, and an
    #: administrator reads why rather than receiving something invented.
    target_kind: Literal["check", "compliance_rule", "field_constraint", "unsupported"] = (
        "unsupported"
    )
    #: For a field constraint: the attribute, the constraint, and its parameter.
    field: str = ""
    constraint: str = ""
    values: list[str] = Field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    pattern: str = ""
    report_kinds: list[str] = Field(default_factory=list)
    #: For a check: an expression over named values, evaluated by code.
    expression: str = ""
    #: For a compliance rule: the fragment every implementing configuration path must
    #: contain, e.g. ``suppressions.deceased``. Without it a compliance rule has nothing
    #: to look for (Phase 6.13a, D3).
    json_path_contains: str = ""
    reasoning: str = ""
    severity: Severity = "medium"
    #: Why it cannot be expressed, when ``target_kind`` is ``unsupported``.
    cannot_express: str = ""
    #: Which numbered statements this rule came from, so a candidate names the
    #: observations that produced it rather than the whole batch (Phase 6.13a, D15).
    from_statements: list[int] = Field(default_factory=list)


class SynthesisResponse(BaseModel):
    """What one synthesis call returns."""

    model_config = ConfigDict(extra="forbid")

    rules: list[SynthesizedRule] = Field(default_factory=list)
    notes: str = ""


class ProgrammeBreach(BaseModel):
    """One programme rule the evidence breaks, in the model's reading (ADR-026)."""

    model_config = ConfigDict(extra="forbid")

    #: The rule's id as listed in the prompt. Code maps it back and sets severity.
    rule_id: int
    #: The evidence quoted: the requirement, config element, or report summary line.
    evidence: str = ""
    reason: str = ""
    confidence: Confidence = 0.5


class ProgrammeRulesResponse(BaseModel):
    """What one programme-rule reading returns. An empty list is a real answer."""

    model_config = ConfigDict(extra="forbid")

    breaches: list[ProgrammeBreach] = Field(default_factory=list)


class MappingReportCell(BaseModel):
    """A report cell the model says evidences a requirement (Phase 6.10)."""

    model_config = ConfigDict(extra="forbid")

    report_key: str = Field(min_length=1)
    sheet: str = ""
    label: str = ""
    cell: str = ""


class MappingComplianceSuggestion(BaseModel):
    """A compliance rule the model suggests when a requirement must always be configured."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    json_path_contains: str = Field(min_length=1)
    reasoning: str = ""


class MappingRequirement(BaseModel):
    """One requirement the model found in an OSL section, with where it answers to."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str = Field(min_length=1, max_length=80)
    requirement_text: str = ""
    config_path: str | None = None
    report_cells: list[MappingReportCell] = Field(default_factory=list)
    validate_text: str = Field(default="", alias="validate")
    comparison: Literal["", "equals", "reconciles"] = ""
    confidence: Confidence = 0.5
    question: str | None = None
    compliance_suggestion: MappingComplianceSuggestion | None = None


class MappingProposal(BaseModel):
    """The mapping interview's answer for one OSL section."""

    model_config = ConfigDict(extra="forbid")

    requirements: list[MappingRequirement] = Field(default_factory=list)


class ClassifyResponse(BaseModel):
    """Which surface a statement an administrator typed belongs on (Phase 6.12b).

    The model places the sentence; it never writes the rule here and never decides
    whether anything passes. ``surface`` is a closed set, so nothing downstream reads
    prose to find out what to do.
    """

    model_config = ConfigDict(extra="forbid")

    #: Where it belongs. ``background`` is a statement that is not a rule at all, and
    #: ``unclear`` is the honest answer when the sentence could be two of the others.
    surface: Literal[
        "field_constraint",
        "check",
        "compliance_rule",
        "background",
        "unclear",
    ] = "unclear"
    #: One sentence saying why, shown to the administrator beside what it became.
    reason: str = ""
    confidence: Confidence = 0.5
    #: What the model needs to know when it cannot place the sentence.
    question: str = ""


class ProgrammeReading(BaseModel):
    """Which delivery programme a set of artifacts reads like (Phase 6.18f).

    Asked only where the keyword check has already failed to find the declared
    programme's words. The model is **not** asked whether the submitter was right:
    that is a comparison, and comparisons are code's (ADR-001). It is asked what the
    documents sound like, and code compares its answer with what was declared.
    """

    model_config = ConfigDict(extra="forbid")

    #: The code of the programme the artifacts read like, from the list supplied in the
    #: prompt, or empty with ``verdict`` ``unclear``. Code checks the code was one it
    #: offered before believing it.
    programme_code: str = ""
    #: ``reads_like`` when the documents plainly describe one of the listed programmes,
    #: ``unclear`` when they do not settle it. Prefer ``unclear`` to a guess: the
    #: keyword check has already failed, so unfamiliar vocabulary is the likely truth
    #: and a confident wrong answer here contradicts a person who was probably right.
    verdict: Literal["reads_like", "unclear"] = "unclear"
    #: The words in the documents that say so, quoted from them. Code shows these to
    #: the reviewer and offers them as keywords, so a guess costs an administrator time.
    phrases: list[str] = Field(default_factory=list, max_length=5)
    reason: str = ""
    confidence: Confidence = 0.5
