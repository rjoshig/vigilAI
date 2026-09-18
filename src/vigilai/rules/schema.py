"""The canonical rule schema, findings, and traces.

One common rule format is the key to the whole design (``docs/design.md`` "Canonical
rule schema"): OSL requirements and config elements are both converted into it, so
comparing them becomes ordinary code rather than a second act of interpretation.

These are Pydantic models because they sit on a boundary: stages 2, 3, and 4 validate
LLM output against them, and invalid model output must fail loudly rather than flow
downstream (standards/python.md, ADR-001).
"""

from __future__ import annotations

from typing import Annotated, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "ReqType",
    "Operator",
    "Action",
    "AppliesTo",
    "Source",
    "Logic",
    "Mode",
    "Severity",
    "FindingType",
    "ReviewStatus",
    "TraceVerdict",
    "LOW_CONFIDENCE",
    "SET_TYPES",
    "Condition",
    "Rule",
    "ConfigElement",
    "Trace",
    "Evidence",
    "Finding",
]

#: What kind of requirement this is. The type decides how values are normalized,
#: compared, and checked in the reports (``docs/design.md`` "Canonical rule schema").
ReqType = Literal[
    "criteria",
    "geography",
    "value_set",
    "attributes",
    "waterfall",
    "quantity",
    "other",
]

#: Comparison operators a condition may use.
Operator = Literal[
    "<", "<=", ">", ">=", "=", "!=", "in", "not_in", "between", "is_null", "not_null"
]

#: What happens to a record that matches the conditions.
Action = Literal["accept", "reject", "tag", "pass"]

#: Which population a rule runs on.
AppliesTo = Literal["all", "accepts", "rejects"]

#: Where a rule came from.
Source = Literal["osl", "config", "user"]

#: How multiple conditions combine.
Logic = Literal["AND", "OR"]

#: Whether a set requirement lists what is allowed or what is forbidden.
Mode = Literal["include", "exclude"]

#: Finding severity. "review" is the bucket for things a person must look at but that
#: are not asserted to be wrong, such as a low-confidence extraction.
Severity = Literal["high", "medium", "low", "review"]

#: Finding types, one per row of the table in ``docs/design.md`` "Findings".
FindingType = Literal[
    "rule_missing_in_config",
    "extra_rule_in_config",
    "value_mismatch",
    "operator_mismatch",
    "waterfall_order_mismatch",
    "report_violates_rule",
    "count_does_not_reconcile",
    "cross_report_disagreement",
    "profile_anomaly",
    "low_confidence_extraction",
    #: The run declared more outputs than the files uploaded cover (ADR-021).
    "deliverables_missing",
    "could_not_evaluate",
]

#: A reviewer's decision on a finding.
ReviewStatus = Literal["undecided", "confirmed", "false_positive", "accepted_risk"]

#: The judge's verdict on whether a config element implements a requirement.
TraceVerdict = Literal["implemented", "partial", "contradicts", "not_related"]

#: Extractions below this confidence are flagged for human review rather than trusted
#: (``docs/design.md`` "Findings": "Rule confidence below 0.7").
LOW_CONFIDENCE: float = 0.7

#: Requirement types whose payload is a set of values rather than numeric conditions.
SET_TYPES: frozenset[str] = frozenset({"geography", "value_set", "attributes"})

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Condition(BaseModel):
    """One field comparison inside a rule.

    Attributes:
        field_name: The canonical attribute name, after alias resolution.
        operator: How the field is compared.
        value: The comparison value. A two-element sequence for ``between``; ``None`` for
            ``is_null`` and ``not_null``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str = Field(min_length=1)
    operator: Operator
    value: float | int | str | Sequence[float | int | str] | None = None

    @model_validator(mode="after")
    def _check_value_matches_operator(self) -> Condition:
        """Reject conditions whose value does not fit the operator.

        Returns:
            The validated condition.

        Raises:
            ValueError: When a null check carries a value, ``between`` does not carry
                exactly two bounds, or a comparison carries no value at all.
        """
        if self.operator in ("is_null", "not_null"):
            if self.value is not None:
                raise ValueError(f"operator {self.operator!r} takes no value")
            return self
        if self.value is None:
            raise ValueError(f"operator {self.operator!r} requires a value")
        if self.operator == "between":
            if not isinstance(self.value, (list, tuple)) or len(self.value) != 2:
                raise ValueError("operator 'between' requires exactly two bounds")
        if self.operator in ("in", "not_in") and not isinstance(self.value, (list, tuple)):
            raise ValueError(f"operator {self.operator!r} requires a sequence of values")
        return self


class Rule(BaseModel):
    """A requirement in canonical form, whatever its origin.

    The same model carries an OSL requirement, a config element's meaning, and a user's
    correction, which is what lets stage 5 compare them with plain code.

    Attributes:
        rule_id: Stable identifier within a run, e.g. ``"R-003"``.
        source: Where the rule came from.
        req_type: Which requirement family this is.
        conditions: Field comparisons, for numeric types.
        logic: How the conditions combine.
        values: The payload for set types (states, value sets, attribute names).
        mode: For set types, whether ``values`` is an allow-list or a deny-list.
        steps: Ordered step names, for ``waterfall``.
        quantity: The number, for ``quantity``.
        applies_to: Which population the rule runs on.
        action: What happens on a match.
        else_action: What happens otherwise.
        tag: The tag applied when ``action`` is ``"tag"``.
        reject_reason: The reason code recorded on rejection.
        waterfall_step: Position in the waterfall, driving count reconciliation.
        source_ref: Where the rule came from, shown as evidence.
        source_text: The originating text, verbatim.
        confidence: The model's self-score; below :data:`LOW_CONFIDENCE` is flagged.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1)
    source: Source
    req_type: ReqType
    conditions: tuple[Condition, ...] = ()
    logic: Logic = "AND"
    values: tuple[str, ...] = ()
    mode: Mode | None = None
    steps: tuple[str, ...] = ()
    quantity: float | None = None
    applies_to: AppliesTo = "all"
    action: Action = "accept"
    else_action: Action | None = None
    tag: str | None = None
    reject_reason: str | None = None
    waterfall_step: int | None = None
    source_ref: str = ""
    source_text: str = ""
    confidence: Confidence = 1.0

    @field_validator("values", mode="before")
    @classmethod
    def _coerce_values(cls, value: object) -> object:
        """Accept a list from JSON and keep tuples immutable.

        Args:
            value: The incoming value.

        Returns:
            The value unchanged; Pydantic performs the tuple conversion.
        """
        return value

    @model_validator(mode="after")
    def _check_payload_matches_type(self) -> Rule:
        """Reject a rule whose payload does not match its ``req_type``.

        A geography rule with no states, or a criteria rule with no conditions, is an
        extraction failure. Catching it here keeps stage 5 free of defensive checks.

        Returns:
            The validated rule.

        Raises:
            ValueError: When the payload does not fit the type.
        """
        if self.req_type in SET_TYPES:
            if not self.values:
                raise ValueError(f"req_type {self.req_type!r} requires 'values'")
            if self.mode is None:
                raise ValueError(f"req_type {self.req_type!r} requires 'mode'")
        elif self.req_type == "criteria":
            if not self.conditions:
                raise ValueError("req_type 'criteria' requires at least one condition")
        elif self.req_type == "waterfall":
            if len(self.steps) < 2:
                raise ValueError("req_type 'waterfall' requires at least two steps")
        elif self.req_type == "quantity" and self.quantity is None:
            raise ValueError("req_type 'quantity' requires 'quantity'")
        return self

    @property
    def is_low_confidence(self) -> bool:
        """Whether this extraction must be flagged for a human.

        Returns:
            ``True`` when confidence is below :data:`LOW_CONFIDENCE`.
        """
        return self.confidence < LOW_CONFIDENCE


class ConfigElement(BaseModel):
    """What one config block does, in requirement vocabulary (stage 3 output).

    Attributes:
        element_id: Stable identifier within a run, e.g. ``"C-019"``.
        json_path: Where the block lives in the config.
        rule: The block's meaning as a canonical rule, when it has one.
        is_technical: Whether the block is plumbing, and so out of the reverse pass.
        description: One plain sentence describing the block.
        confidence: The model's self-score.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    element_id: str = Field(min_length=1)
    json_path: str = Field(min_length=1)
    rule: Rule | None = None
    is_technical: bool = False
    description: str = ""
    confidence: Confidence = 1.0

    @model_validator(mode="after")
    def _technical_blocks_need_no_rule(self) -> ConfigElement:
        """Require a rule for anything that is not technical.

        Returns:
            The validated element.

        Raises:
            ValueError: When a non-technical element carries no rule, which would make it
                invisible to the reverse pass.
        """
        if not self.is_technical and self.rule is None:
            raise ValueError(f"non-technical element {self.element_id!r} requires a rule")
        return self


class Trace(BaseModel):
    """A link between an OSL requirement and a config element (stage 4 output).

    Attributes:
        rule_id: The OSL requirement.
        element_id: The config element, or ``None`` when nothing implements it.
        verdict: The judge's answer.
        reason: Why, in one sentence. Shown as evidence.
        confidence: The judge's self-score.
        by_code: Whether code linked this without asking the model, which happens on an
            exact match and saves a call (``docs/design.md`` "LLM cost controls").
        edited_by: Who corrected the link, when a user did.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str = Field(min_length=1)
    element_id: str | None = None
    verdict: TraceVerdict
    reason: str = ""
    confidence: Confidence = 1.0
    by_code: bool = False
    edited_by: str | None = None

    @model_validator(mode="after")
    def _unlinked_traces_are_not_implemented(self) -> Trace:
        """Keep "nothing implements this" and "this implements it" distinguishable.

        Returns:
            The validated trace.

        Raises:
            ValueError: When a verdict claims an implementation but names no element.
        """
        if self.element_id is None and self.verdict != "not_related":
            raise ValueError(f"verdict {self.verdict!r} requires an element_id")
        return self


class Evidence(BaseModel):
    """Where a finding can be seen, in each of the three artefacts.

    Every finding stores all three pointers so the review screen can show the OSL text,
    the config value, and the report cell side by side (``docs/design.md`` "Findings").

    Attributes:
        osl_ref: The OSL location, e.g. ``"OSL section 3 Geography"``.
        osl_text: The originating sentence, verbatim.
        config_path: The config JSON path.
        config_value: The value at that path, rendered.
        report_name: Which report the value came from.
        report_sheet: Which sheet.
        report_cell: The A1-style address.
        report_value: The value in that cell, rendered.
        sample_rows: Row numbers in the DIRT sample tab, never the row contents (ADR-003).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    osl_ref: str = ""
    osl_text: str = ""
    config_path: str = ""
    config_value: str = ""
    report_name: str = ""
    report_sheet: str = ""
    report_cell: str = ""
    report_value: str = ""
    sample_rows: tuple[int, ...] = ()


class Finding(BaseModel):
    """One potential issue, with its evidence and its review state.

    Attributes:
        finding_id: Stable identifier within a run, e.g. ``"F-01"``.
        type: Which kind of issue this is.
        severity: How serious.
        title: One line, shown in the findings list.
        detail: The explanation, including the exact members that differ.
        leg: Which leg of the three-way reconciliation broke.
        rule_id: The requirement involved, when there is one.
        element_id: The config element involved, when there is one.
        evidence: Where to see it.
        rules_version: Which rules version produced this, so old reports stay reproducible.
        review_status: The reviewer's decision.
        review_note: The reviewer's comment, shown in the final report for Not OK items.
        verified: Whether stage 8 re-checked this finding.
        verify_agreed: Whether the second opinion agreed. Disagreement downgrades the
            severity to ``"review"`` rather than dropping the finding.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str = Field(min_length=1)
    type: FindingType
    severity: Severity
    title: str = Field(min_length=1)
    detail: str = ""
    leg: Literal["osl_config", "config_reports", "osl_reports"] = "osl_config"
    rule_id: str | None = None
    element_id: str | None = None
    evidence: Evidence = Evidence()
    rules_version: int = 1
    review_status: ReviewStatus = "undecided"
    review_note: str = ""
    verified: bool = False
    verify_agreed: bool | None = None

    @property
    def needs_decision(self) -> bool:
        """Whether the finalize gate is waiting on this finding.

        The gate is: every high-severity finding needs a decision (ADR-015).

        Returns:
            ``True`` when this is a high-severity finding with no decision yet.
        """
        return self.severity == "high" and self.review_status == "undecided"
