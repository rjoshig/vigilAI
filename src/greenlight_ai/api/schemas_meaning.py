"""Wire models for Meaning (Phase 6.10, ADR-033)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MeaningBulkIn",
    "MeaningEntryIn",
    "MeaningEntryOut",
    "MeaningEntryPatch",
    "MeaningSamplesOut",
    "ProposeIn",
    "ProposeOut",
    "ReportCellIn",
]

Status = Literal["proposed", "open", "confirmed", "rejected"]
Comparison = Literal["", "equals", "reconciles"]


class ReportCellIn(BaseModel):
    """Where in a report a requirement is evidenced."""

    model_config = ConfigDict(extra="forbid")

    report_key: str = Field(min_length=1)
    sheet: str = ""
    kind: Literal["cell", "label"] = "label"
    cell: str = ""
    label: str = ""
    label_column: int = 0
    value_column: int = 1


class MeaningEntryIn(BaseModel):
    """A requirement mapping written by hand."""

    model_config = ConfigDict(extra="forbid")

    scope_code: str = ""
    key: str = Field(min_length=1, max_length=80)
    osl_section: str = ""
    osl_phrase: str = ""
    requirement_text: str = ""
    config_path: str = ""
    report_cells: list[ReportCellIn] = Field(default_factory=list)
    meaning: str = ""
    validate_text: str = Field(default="", alias="validate")
    comparison: Comparison = ""
    tolerance: float = 0.0
    note: str = ""
    compliance_suggestion: Optional[dict[str, str]] = None


class MeaningEntryPatch(BaseModel):
    """An edit, a decision, or both, on one entry."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[Status] = None
    osl_section: Optional[str] = None
    osl_phrase: Optional[str] = None
    requirement_text: Optional[str] = None
    config_path: Optional[str] = None
    report_cells: Optional[list[ReportCellIn]] = None
    meaning: Optional[str] = None
    validate_text: Optional[str] = Field(default=None, alias="validate")
    comparison: Optional[Comparison] = None
    tolerance: Optional[float] = None
    note: Optional[str] = None
    compliance_suggestion: Optional[dict[str, str]] = None
    #: Explicitly drop a suggestion the model made.
    drop_compliance_suggestion: bool = False


class MeaningEntryOut(BaseModel):
    """One entry, as the Meaning screen shows it."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    scope_code: str
    key: str
    osl_section: str
    osl_phrase: str
    requirement_text: str
    config_path: str
    report_cells: list[dict[str, Any]]
    meaning: str
    validate_text: str = Field(alias="validate")
    comparison: str
    tolerance: float
    examples: list[dict[str, Any]]
    compliance_suggestion: Optional[dict[str, Any]]
    status: str
    question: str
    note: str
    confidence: float
    proposed_by: str
    confirmed_by: str
    confirmed_at: Optional[dt.datetime]
    updated_at: dt.datetime
    #: Whether a shadow check / compliance rule currently exists for it.
    compiled_check: bool = False
    compiled_compliance: bool = False


class ProposeIn(BaseModel):
    """Run the interview for one scope."""

    model_config = ConfigDict(extra="forbid")

    scope_code: str = ""


class ProposeOut(BaseModel):
    """What the interview did."""

    sections: int
    proposed: int
    open: int
    updated: int
    skipped_confirmed: int
    calls: int
    cached: int


class MeaningBulkIn(BaseModel):
    """One decision on several entries; ``delete`` needs the typed word (ADR-032)."""

    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1, max_length=500)
    action: Literal["confirm", "reject", "delete"]
    confirm: str = ""


class MeaningSampleOut(BaseModel):
    """A sample the scope reads, and whether it is the programme's own or global."""

    artifact_key: str
    label: str
    sample_id: int
    scope_code: str
    filename: str


class MeaningSamplesOut(BaseModel):
    """The samples in scope, and what is missing for an interview."""

    samples: list[MeaningSampleOut] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
