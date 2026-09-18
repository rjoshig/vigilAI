"""Admin-defined checks and compliance rules, as data.

Cross-report number checks are defined by admins as data, not code: the LLM helps write
a check once, and code runs it on every request at no token cost (``docs/design.md``
"Configurable checks"). This module holds the definitions; :mod:`vigilai.checks.runner`
runs them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from vigilai.rules.schema import Severity

__all__ = ["CheckKind", "CheckDefinition", "ComplianceRule", "ReversePassCategory"]

CheckKind = Literal["expression", "judgment"]


@dataclass(frozen=True, slots=True)
class CheckDefinition:
    """One admin-defined cross-report check.

    Attributes:
        name: The check's identifier, shown on findings.
        version: Bumped on every edit, so a finding records which version produced it.
        kind: ``"expression"`` for a formula, ``"judgment"`` for one the LLM answers.
        expression: The formula, for ``"expression"`` checks.
        instruction: What to judge, for ``"judgment"`` checks.
        reasoning: The plain-English reason shown to users on a failure.
        severity: How serious a failure is.
        scope: ``"all"`` or a customer name.
        is_active: Whether the check runs.
    """

    name: str
    version: int = 1
    kind: CheckKind = "expression"
    expression: str = ""
    instruction: str = ""
    reasoning: str = ""
    severity: Severity = "medium"
    scope: str = "all"
    is_active: bool = True

    def applies_to(self, customer: str) -> bool:
        """Whether this check runs for a customer.

        Args:
            customer: The run's customer name.

        Returns:
            ``True`` when the check is active and in scope.
        """
        return self.is_active and self.scope in ("all", customer)


@dataclass(frozen=True, slots=True)
class ComplianceRule:
    """A rule that must be present in every config in scope.

    Compliance rules work the other way round from OSL requirements: each one must
    appear in the config even if the OSL never mentions it (``docs/design.md``
    "Processing pipeline", step 6).

    Attributes:
        name: The rule's identifier.
        json_path_contains: A fragment the implementing config path must contain.
        expected_value: The value the config must set, when there is one.
        scope: ``"all"`` or a customer name.
        reasoning: Why the rule exists, shown on a finding.
        is_active: Whether the rule is enforced.
    """

    name: str
    json_path_contains: str
    expected_value: object = True
    scope: str = "all"
    reasoning: str = ""
    is_active: bool = True

    def applies_to(self, customer: str) -> bool:
        """Whether this rule is enforced for a customer.

        Args:
            customer: The run's customer name.

        Returns:
            ``True`` when the rule is active and in scope.
        """
        return self.is_active and self.scope in ("all", customer)


@dataclass(frozen=True, slots=True)
class ReversePassCategory:
    """One category of config element that is checked back against the OSL.

    The reverse pass is scoped, not exhaustive, because the OSL does not describe every
    detail of the extract process. Only the checked categories are traced back; the rest
    is ignored (``docs/design.md`` "Processing pipeline", step 6).

    Attributes:
        name: The category name, shown in the admin-ui.
        kinds: Config key families in this category, e.g. ``("filters", "rules")``.
        checked: Whether elements in this category are reverse-checked.
    """

    name: str
    kinds: tuple[str, ...]
    checked: bool = True


#: The default category list, matching the admin-ui mock. Phase 4 moves this to the
#: database; until then it is the shipped default.
DEFAULT_CATEGORIES: Sequence[ReversePassCategory] = (
    ReversePassCategory("Filters and select criteria", ("filters", "rules"), checked=True),
    ReversePassCategory("Model data and attributes", ("output", "models"), checked=True),
    ReversePassCategory("Fixed compliance rules", ("suppressions",), checked=True),
    ReversePassCategory("Technical", ("source", "sink", "logging", "runtime"), checked=False),
    ReversePassCategory("Scheduling and retries", ("schedule", "retry"), checked=False),
)


@dataclass(frozen=True, slots=True)
class AdminConfig:
    """Everything the admin-ui contributes to a run.

    Attributes:
        checks: Cross-report checks.
        compliance_rules: Rules that must be present in the config.
        categories: Reverse-pass scoping.
        named_values: Pointers the checks refer to by name.
    """

    checks: tuple[CheckDefinition, ...] = ()
    compliance_rules: tuple[ComplianceRule, ...] = ()
    categories: tuple[ReversePassCategory, ...] = tuple(DEFAULT_CATEGORIES)
    named_values: tuple[object, ...] = field(default_factory=tuple)
