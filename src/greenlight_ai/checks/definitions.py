"""Admin-defined checks and compliance rules, as data.

Cross-report number checks are defined by admins as data, not code: the LLM helps write
a check once, and code runs it on every request at no token cost (``docs/design.md``
"Configurable checks"). This module holds the definitions; stage 6 evaluates the
compliance rules and stage 7 the checks (:mod:`greenlight_ai.pipeline.s6_reverse`,
:mod:`greenlight_ai.pipeline.s7_reports`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from greenlight_ai import scopes
from greenlight_ai.rules.schema import Severity

__all__ = [
    "CheckKind",
    "CheckDefinition",
    "ComplianceRule",
    "ReversePassCategory",
    "in_scope",
]

CheckKind = Literal["expression", "judgment"]


def in_scope(scope: str, customer: str, programme_code: str = "") -> bool:
    """Decide whether a definition's scope covers a run.

    Args:
        scope: Any scope token; :mod:`greenlight_ai.scopes` decides what it means.
        customer: The run's customer name.
        programme_code: The run's delivery programme code, when it has one.

    Returns:
        ``True`` when the scope covers the run. The scope string is not interpreted
        here: one module reads a scope, so a definition cannot be in scope on one
        screen and out of scope in the pipeline.
    """
    return scopes.covers(scope, customer, programme_code)


@dataclass(frozen=True, slots=True)
class CheckDefinition:
    """One admin-defined cross-report check.

    Attributes:
        name: The check's identifier, shown on findings.
        version: Bumped on every edit, so a finding records which version produced it.
        kind: ``"expression"`` for a formula, ``"judgment"`` for one the LLM answers.
        expression: The formula, for ``"expression"`` checks.
        instruction: What to judge, for ``"judgment"`` checks.
        value_names: For a judgment check, the named values the model is shown and
            nothing else (ADR-039).
        reasoning: The plain-English reason shown to users on a failure.
        severity: How serious a failure is.
        scope: Where it applies, as a :mod:`greenlight_ai.scopes` token.
        is_active: Whether the check's findings count.
        id: The stored row, so a finding can name the rule behind it.
        state: The lifecycle state (ADR-021). A ``shadow`` check runs and its
            findings are recorded and shown to nobody.
    """

    name: str
    version: int = 1
    id: int | None = None
    state: str = "active"
    kind: CheckKind = "expression"
    expression: str = ""
    instruction: str = ""
    value_names: tuple[str, ...] = ()
    reasoning: str = ""
    severity: Severity = "medium"
    scope: str = scopes.EVERYWHERE
    is_active: bool = True

    def applies_to(self, customer: str, programme_code: str = "") -> bool:
        """Whether this check runs for a run.

        Args:
            customer: The run's customer name.
            programme_code: The run's delivery programme code.

        Returns:
            ``True`` when the check is active or in shadow, and in scope.
        """
        runs = self.is_active or self.state == "shadow"
        return runs and in_scope(self.scope, customer, programme_code)


@dataclass(frozen=True, slots=True)
class ComplianceRule:
    """A rule that must be present in every config in scope.

    Compliance rules work the other way round from OSL requirements: each one must
    appear in the config even if the OSL never mentions it (``docs/design.md``
    "Processing pipeline", step 6).

    Attributes:
        name: The rule's identifier.
        json_path_contains: The configuration path that implements the rule.
            Matched by :mod:`greenlight_ai.checks.compliance_match`, which
            tolerates a different spelling and an extra level of nesting.
        alternates: Other paths that also count, written by an administrator for
            the case normalising does not reach — a customer whose OFAC screening
            is called ``suppressions.sdn_screening`` (Phase 6.15).
        expected_value: The value the config must set, when there is one.
        scope: Where it applies, as a :mod:`greenlight_ai.scopes` token.
        reasoning: Why the rule exists, shown on a finding.
        is_active: Whether the rule is enforced.
        id: The stored row, so a finding can name the rule behind it.
        state: The lifecycle state (ADR-021). A ``shadow`` rule runs and its findings
            are recorded and shown to nobody.
    """

    name: str
    json_path_contains: str
    alternates: tuple[str, ...] = ()
    expected_value: object = True
    scope: str = scopes.EVERYWHERE
    reasoning: str = ""
    is_active: bool = True
    id: int | None = None
    state: str = "active"

    def applies_to(self, customer: str, programme_code: str = "") -> bool:
        """Whether this rule is enforced for a run.

        Args:
            customer: The run's customer name.
            programme_code: The run's delivery programme code.

        Returns:
            ``True`` when the rule is active or in shadow, and in scope. Until 6.13a
            this demanded ``is_active`` alone, so a learned compliance rule sat in
            shadow forever with nothing to show for it.
        """
        runs = self.is_active or self.state == "shadow"
        return runs and in_scope(self.scope, customer, programme_code)


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
        field_constraints: Per-attribute rules, written in plain words by a reviewer
            and stored as structured data (ADR-021).
        shadow_rule_refs: Which rules are still in shadow, as ``kind:id``. Their
            findings are recorded and counted but shown to nobody, so a new rule's
            precision can be measured before it interrupts a reviewer.
    """

    checks: tuple[CheckDefinition, ...] = ()
    compliance_rules: tuple[ComplianceRule, ...] = ()
    categories: tuple[ReversePassCategory, ...] = tuple(DEFAULT_CATEGORIES)
    named_values: tuple[object, ...] = field(default_factory=tuple)
    field_constraints: tuple[object, ...] = field(default_factory=tuple)
    shadow_rule_refs: frozenset[str] = frozenset()
