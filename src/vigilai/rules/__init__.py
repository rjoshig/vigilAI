"""The canonical rule schema, normalizers, and derived report checks.

The LLM reads and judges meaning; everything in this package is deterministic code
(ADR-001).
"""

from vigilai.rules.derive import INVERSE_OPERATOR, CheckKind, DerivedCheck, derive_checks
from vigilai.rules.normalize import (
    STATE_CODES,
    AliasTable,
    Interval,
    interval_from_condition,
    normalize_field_name,
    normalize_state,
    normalize_states,
    parse_number,
)
from vigilai.rules.schema import (
    LOW_CONFIDENCE,
    SET_TYPES,
    Action,
    AppliesTo,
    Condition,
    ConfigElement,
    Evidence,
    Finding,
    FindingType,
    Logic,
    Mode,
    Operator,
    ReqType,
    ReviewStatus,
    Rule,
    Severity,
    Source,
    Trace,
    TraceVerdict,
)

__all__ = [
    "Action",
    "AliasTable",
    "AppliesTo",
    "CheckKind",
    "Condition",
    "ConfigElement",
    "DerivedCheck",
    "Evidence",
    "Finding",
    "FindingType",
    "INVERSE_OPERATOR",
    "Interval",
    "LOW_CONFIDENCE",
    "Logic",
    "Mode",
    "Operator",
    "ReqType",
    "ReviewStatus",
    "Rule",
    "SET_TYPES",
    "STATE_CODES",
    "Severity",
    "Source",
    "Trace",
    "TraceVerdict",
    "derive_checks",
    "interval_from_condition",
    "normalize_field_name",
    "normalize_state",
    "normalize_states",
    "parse_number",
]
