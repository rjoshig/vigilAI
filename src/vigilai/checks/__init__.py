"""Report checks, admin-defined checks, and the safe expression evaluator.

Everything here is deterministic code (ADR-001). A check that cannot be evaluated
produces a finding, never a silent skip.
"""

from vigilai.checks.definitions import (
    DEFAULT_CATEGORIES,
    AdminConfig,
    CheckDefinition,
    ComplianceRule,
    ReversePassCategory,
)
from vigilai.checks.expressions import (
    ALLOWED_FUNCTIONS,
    EvaluationResult,
    ExpressionError,
    UnresolvedValue,
    evaluate,
    referenced_names,
)
from vigilai.checks.named_values import NamedValue, resolve, resolve_all, to_number
from vigilai.checks.reports import (
    REPORT_CHECKED_KINDS,
    AttributeStat,
    CheckOutcome,
    attribute_stats,
    run_derived_check,
)

__all__ = [
    "ALLOWED_FUNCTIONS",
    "AdminConfig",
    "AttributeStat",
    "CheckDefinition",
    "CheckOutcome",
    "ComplianceRule",
    "DEFAULT_CATEGORIES",
    "EvaluationResult",
    "ExpressionError",
    "NamedValue",
    "REPORT_CHECKED_KINDS",
    "ReversePassCategory",
    "UnresolvedValue",
    "attribute_stats",
    "evaluate",
    "referenced_names",
    "resolve",
    "resolve_all",
    "run_derived_check",
    "to_number",
]
