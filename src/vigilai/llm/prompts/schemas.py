"""Pydantic schemas for LLM output.

These sit on the boundary: a model answer that does not validate is retried once and
then fails loudly rather than flowing downstream (standards/python.md). They are
deliberately narrower than the canonical rule schema, because a stage asks for exactly
what it needs and the pipeline builds the canonical object from the answer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vigilai.rules.schema import Confidence, Mode, Operator, ReqType, TraceVerdict

__all__ = [
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
