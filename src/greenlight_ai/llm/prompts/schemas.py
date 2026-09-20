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
    "SummarizeResponse",
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
    reasoning: str = ""
    severity: Severity = "medium"
    #: Why it cannot be expressed, when ``target_kind`` is ``unsupported``.
    cannot_express: str = ""


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
