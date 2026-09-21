"""Evaluating field constraints (ADR-021).

"This field is never blank for account review" is what people actually say. The
sentence is the input to synthesis; what runs is this: structured data compared by
code, because the model reads meaning and code does every comparison (ADR-001).

Each constraint is checked against whatever report carries the field, matched through
the alias table so a name that differs between the OSL and the workbook still lines
up.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final, Iterable, Mapping, Sequence

from greenlight_ai.parsers.base import ReportDocument, ReportKind
from greenlight_ai.resolve import attributes as attribute_match
from greenlight_ai.rules.normalize import AliasTable

__all__ = ["FieldConstraintSpec", "ConstraintOutcome", "evaluate", "CONSTRAINT_KINDS"]

_LOG: Final = logging.getLogger(__name__)

#: The constraints a person can express and code can check. Anything outside this is
#: not a field constraint: it is a check, and it belongs in the expression evaluator.
CONSTRAINT_KINDS: Final[tuple[str, ...]] = (
    "not_blank",
    "allowed_values",
    "forbidden_values",
    "range",
    "format",
    "fill_rate_min",
)


@dataclass(frozen=True, slots=True)
class FieldConstraintSpec:
    """One constraint, as stored.

    Attributes:
        id: The row id, so a finding can point back at the rule.
        field: The canonical attribute name.
        constraint: One of :data:`CONSTRAINT_KINDS`.
        value: The parameter, shaped by the constraint: a list for the value
            constraints, ``{"min": .., "max": ..}`` for a range, a pattern for a
            format, a number for a fill rate.
        report_kinds: Which reports to look in. Empty means every report carrying
            the field.
        severity: The severity of a violation.
        reasoning: Why the constraint exists, shown with the finding.
    """

    id: int
    field: str
    constraint: str
    value: Any
    report_kinds: Sequence[str] = ()
    severity: str = "medium"
    reasoning: str = ""


@dataclass(frozen=True, slots=True)
class ConstraintOutcome:
    """What checking one constraint found.

    Attributes:
        spec: The constraint checked.
        passed: True, False, or None when it could not be evaluated. None is never a
            silent skip: it becomes a "could not evaluate" finding, because a
            constraint nobody could check is a thing the reviewer should know.
        detail: A sentence a reviewer can act on.
        report_kind: Which report it looked at.
        sheet: Which sheet.
        offending: Up to a few offending values, for the evidence. Aggregates only,
            never a row (ADR-003).
    """

    spec: FieldConstraintSpec
    passed: bool | None
    detail: str
    report_kind: str = ""
    sheet: str = ""
    offending: tuple[str, ...] = ()


#: How many offending values to carry into a finding. Enough to recognise the
#: problem, few enough that the evidence stays a summary.
_MAX_OFFENDING: Final[int] = 5


def _columns(
    document: ReportDocument, field: str, aliases: AliasTable
) -> list[tuple[str, tuple[Any, ...]]]:
    """Find the field's column in a report, under any of its names.

    Args:
        document: The parsed report.
        field: The canonical attribute name.
        aliases: The alias table.

    Returns:
        One entry per sheet that carries the field: the sheet name and its values.
    """
    found: list[tuple[str, tuple[Any, ...]]] = []
    for sheet in document.sheets:
        # The third copy of "does this artifact carry this attribute", and the reason
        # it now goes through one helper: tolerance added for the DIRT used to leave
        # this one matching on equality alone (Phase 6.22a).
        match = attribute_match.present(field, tuple(sheet.header), canonical=aliases.resolve)
        if not match.resolved or match.found is None:
            continue
        found.append((sheet.name, tuple(cell.value for cell in sheet.column(match.found))))
    return found


def _blank(value: Any) -> bool:
    """Whether a cell counts as empty.

    Args:
        value: The cell value.

    Returns:
        Whether it is None or whitespace. A zero is a value, not a blank, which is
        the distinction this exists to get right.
    """
    return value is None or (isinstance(value, str) and not value.strip())


def _check_values(
    spec: FieldConstraintSpec, values: Iterable[Any]
) -> tuple[bool | None, str, tuple[str, ...]]:
    """Apply one constraint to a column's values.

    Args:
        spec: The constraint.
        values: The column's values.

    Returns:
        Whether it held, a sentence explaining, and the offending values.
    """
    items = list(values)
    if not items:
        return None, "the column is present but empty", ()

    if spec.constraint == "not_blank":
        blanks = sum(1 for value in items if _blank(value))
        if blanks:
            return (
                False,
                f"{blanks} of {len(items)} values are blank",
                ("blank",),
            )
        return True, f"all {len(items)} values are populated", ()

    if spec.constraint == "fill_rate_min":
        try:
            minimum = float(spec.value)
        except (TypeError, ValueError):
            return None, f"{spec.value!r} is not a fill rate", ()
        filled = sum(1 for value in items if not _blank(value))
        rate = filled / len(items) * 100
        if rate + 1e-9 < minimum:
            return False, f"{rate:.1f}% populated, below the required {minimum:.1f}%", ()
        return True, f"{rate:.1f}% populated", ()

    present = {str(value).strip() for value in items if not _blank(value)}

    if spec.constraint == "allowed_values":
        allowed = {str(item).strip() for item in spec.value or []}
        if not allowed:
            return None, "no allowed values are configured", ()
        extra = sorted(present - allowed)
        if extra:
            return (
                False,
                f"{len(extra)} value(s) are outside the allowed set",
                tuple(extra[:_MAX_OFFENDING]),
            )
        return True, f"every value is one of the {len(allowed)} allowed", ()

    if spec.constraint == "forbidden_values":
        forbidden = {str(item).strip() for item in spec.value or []}
        hit = sorted(present & forbidden)
        if hit:
            return (
                False,
                f"{len(hit)} forbidden value(s) are present",
                tuple(hit[:_MAX_OFFENDING]),
            )
        return True, "no forbidden value is present", ()

    if spec.constraint == "range":
        bounds = spec.value if isinstance(spec.value, Mapping) else {}
        low, high = bounds.get("min"), bounds.get("max")
        outside: list[str] = []
        for value in items:
            if _blank(value):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                outside.append(str(value))
                continue
            if (low is not None and number < float(low)) or (
                high is not None and number > float(high)
            ):
                outside.append(str(value))
        if outside:
            return (
                False,
                f"{len(outside)} value(s) fall outside {low} to {high}",
                tuple(outside[:_MAX_OFFENDING]),
            )
        return True, f"every value is within {low} to {high}", ()

    if spec.constraint == "format":
        try:
            pattern = re.compile(str(spec.value))
        except re.error as exc:
            return None, f"the format is not a usable pattern: {exc}", ()
        bad = sorted(value for value in present if not pattern.fullmatch(value))
        if bad:
            return (
                False,
                f"{len(bad)} value(s) do not match the required format",
                tuple(bad[:_MAX_OFFENDING]),
            )
        return True, "every value matches the required format", ()

    return None, f"{spec.constraint!r} is not a constraint this version can check", ()


def evaluate(
    specs: Sequence[FieldConstraintSpec],
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable,
) -> list[ConstraintOutcome]:
    """Check every constraint against the reports that carry its field.

    Args:
        specs: The constraints in scope.
        reports: The parsed reports.
        aliases: The alias table, so a name that differs between artefacts still
            lines up.

    Returns:
        One outcome per constraint and report it applies to. A constraint whose field
        appears in no report yields a single outcome with ``passed`` of ``None``,
        never silence: a rule nobody could check is something the reviewer should be
        told about.
    """
    outcomes: list[ConstraintOutcome] = []
    for spec in specs:
        wanted = set(spec.report_kinds or ())
        looked = False
        for kind, document in reports.items():
            if wanted and kind not in wanted:
                continue
            for sheet_name, values in _columns(document, spec.field, aliases):
                looked = True
                passed, detail, offending = _check_values(spec, values)
                outcomes.append(
                    ConstraintOutcome(
                        spec=spec,
                        passed=passed,
                        detail=detail,
                        report_kind=str(kind),
                        sheet=sheet_name,
                        offending=offending,
                    )
                )
        if not looked:
            outcomes.append(
                ConstraintOutcome(
                    spec=spec,
                    passed=None,
                    detail=f"no uploaded report carries a column for {spec.field!r}",
                )
            )
    return outcomes
