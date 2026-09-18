"""Wire models for the admin API (Phase 4).

Separate from `schemas.py` because the admin surface is a different audience with a
different shape: it edits configuration, where the run surface reads results.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "TemplateOut",
    "NamedValueIn",
    "NamedValueOut",
    "CheckIn",
    "CheckOut",
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
LocatorKind = Literal["cell", "label"]


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
    reasoning: str = ""
    severity: Severity = "medium"
    scope: str = "all"
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
    scope: str = "all"
    reasoning: str = ""
    is_active: bool = True


class ComplianceRuleOut(ComplianceRuleIn):
    """A stored compliance rule."""

    id: int


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
