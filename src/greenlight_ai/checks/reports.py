"""Report checks: does the delivery actually obey the rule?

Each requirement type has a fixed report check (``docs/design.md`` "Processing
pipeline", step 7). Geography: every state in the distribution must be in the allowed
set. Criteria: the DIRT min and max must respect the interval. Attributes: the requested
fields must exist. Waterfall: the counts must reconcile.

All of it is code (ADR-001). The derived checks in :mod:`greenlight_ai.rules.derive` say what
to assert; this module finds the number in the report and asserts it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Mapping

from greenlight_ai.checks.named_values import to_number
from greenlight_ai.parsers.base import ReportDocument, ReportKind
from greenlight_ai.rules.derive import DerivedCheck
from greenlight_ai.rules.normalize import AliasTable, normalize_field_name

__all__ = [
    "CheckOutcome",
    "run_derived_check",
    "attribute_stats",
    "AttributeStat",
    "REPORT_CHECKED_KINDS",
]

_LOG: Final = logging.getLogger(__name__)

#: Where each report check looks. Keeping the layout assumptions in one table makes the
#: in-house adjustment in Phase 6 a data change rather than a code change.
DIRT_ATTRIBUTE_SHEET: Final[str] = "Attributes"
STATE_SHEET: Final[str] = "States"
FIELD_SHEET: Final[str] = "Fields"
FLOW_SHEET: Final[str] = "Flow"

#: Derived-check kinds a report can answer. ``step_order`` is deliberately absent: the
#: order of the waterfall is settled between the OSL and the config in stage 5, and the
#: counts report shows totals per step, not the order they ran in. Treating it as a
#: report check produced a "could not evaluate" finding on every run.
REPORT_CHECKED_KINDS: Final[frozenset[str]] = frozenset(
    {
        "min_at_least",
        "min_greater_than",
        "max_at_most",
        "max_less_than",
        "value_set_subset",
        "value_set_excludes",
        "fields_present",
        "counts_reconcile",
        "count_equals",
    }
)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """What a report check concluded.

    Attributes:
        passed: Whether the delivery obeys the rule. ``None`` when the check could not
            be evaluated, which is a finding of its own, never a silent skip.
        detail: What was compared, in words.
        report_kind: Which report the evidence came from.
        sheet: Which sheet.
        cell: The cell address, when a single cell carried the value.
        observed: What the report showed.
    """

    passed: bool | None
    detail: str
    report_kind: ReportKind | None = None
    sheet: str = ""
    cell: str = ""
    observed: str = ""


@dataclass(frozen=True, slots=True)
class AttributeStat:
    """One row of the DIRT attribute sheet.

    Attributes:
        name: The attribute name as the report writes it.
        minimum: The delivered minimum, when numeric.
        maximum: The delivered maximum, when numeric.
        address: The address of the row's first cell, for evidence.
    """

    name: str
    minimum: float | None
    maximum: float | None
    address: str


def attribute_stats(
    reports: Mapping[ReportKind, ReportDocument], aliases: AliasTable | None = None
) -> dict[str, AttributeStat]:
    """Read the per-attribute statistics out of the DIRT.

    Args:
        reports: The parsed reports.
        aliases: The attribute alias table. The DIRT names a column ``SCORE_V3`` where
            the OSL says "score"; without resolving both sides the check cannot find
            the attribute it is meant to assert on.

    Returns:
        Canonical attribute name to its statistics, empty when the DIRT is absent.
    """
    resolve = aliases.resolve if aliases is not None else normalize_field_name
    dirt = reports.get("dirt")
    if dirt is None:
        return {}
    sheet = dirt.sheet(DIRT_ATTRIBUTE_SHEET)
    if sheet is None:
        return {}

    header = [h.strip().lower() for h in sheet.header]
    try:
        name_index = header.index("attribute")
    except ValueError:
        return {}
    min_index = header.index("min") if "min" in header else None
    max_index = header.index("max") if "max" in header else None

    stats: dict[str, AttributeStat] = {}
    for row in sheet.rows:
        if name_index >= len(row) or row[name_index].value is None:
            continue
        name = str(row[name_index].value).strip()
        stats[resolve(name)] = AttributeStat(
            name=name,
            minimum=(
                to_number(row[min_index].value)
                if min_index is not None and min_index < len(row)
                else None
            ),
            maximum=(
                to_number(row[max_index].value)
                if max_index is not None and max_index < len(row)
                else None
            ),
            address=row[name_index].address,
        )
    return stats


def run_derived_check(
    check: DerivedCheck,
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable | None = None,
) -> CheckOutcome:
    """Run one derived check against the reports.

    Args:
        check: What the rule implies the reports must show.
        reports: The parsed reports.
        aliases: The attribute alias table, used to match the OSL's wording against the
            report's column names.

    Returns:
        The outcome. ``passed`` is ``None`` when the report the check needs is absent,
        which becomes a ``could_not_evaluate`` finding. Callers filter on
        :data:`REPORT_CHECKED_KINDS` first, so a non-report kind never reaches here.
    """
    if check.kind in ("min_at_least", "min_greater_than", "max_at_most", "max_less_than"):
        return _check_bound(check, reports, aliases)
    if check.kind in ("value_set_subset", "value_set_excludes"):
        return _check_value_set(check, reports)
    if check.kind == "fields_present":
        return _check_fields_present(check, reports, aliases)
    if check.kind == "counts_reconcile":
        return _check_counts_reconcile(reports)
    if check.kind == "count_equals":
        return _check_count_equals(check, reports)
    return CheckOutcome(passed=None, detail=f"No report check implements {check.kind!r}.")


def _check_bound(
    check: DerivedCheck,
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable | None = None,
) -> CheckOutcome:
    """Assert a delivered minimum or maximum respects the rule's bound.

    Args:
        check: The derived check.
        reports: The parsed reports.
        aliases: The attribute alias table.

    Returns:
        The outcome.
    """
    stats = attribute_stats(reports, aliases)
    if not stats:
        return CheckOutcome(passed=None, detail="The DIRT attribute sheet was not available.")

    resolve = aliases.resolve if aliases is not None else normalize_field_name
    stat = stats.get(resolve(check.field_name))
    if stat is None:
        return CheckOutcome(
            passed=None,
            detail=f"{check.field_name} does not appear in the DIRT attribute sheet.",
            report_kind="dirt",
            sheet=DIRT_ATTRIBUTE_SHEET,
        )

    wants_min = check.kind.startswith("min")
    observed = stat.minimum if wants_min else stat.maximum
    if observed is None or check.value is None:
        return CheckOutcome(
            passed=None,
            detail=f"The DIRT gives no {'minimum' if wants_min else 'maximum'} for {stat.name}.",
            report_kind="dirt",
            sheet=DIRT_ATTRIBUTE_SHEET,
            cell=stat.address,
        )

    passed = {
        "min_at_least": observed >= check.value,
        "min_greater_than": observed > check.value,
        "max_at_most": observed <= check.value,
        "max_less_than": observed < check.value,
    }[check.kind]
    comparison = {
        "min_at_least": ">=",
        "min_greater_than": ">",
        "max_at_most": "<=",
        "max_less_than": "<",
    }[check.kind]
    return CheckOutcome(
        passed=passed,
        detail=(
            f"{stat.name} delivered {'minimum' if wants_min else 'maximum'} is {observed:g}; "
            f"the OSL requires {comparison} {check.value:g}."
        ),
        report_kind="dirt",
        sheet=DIRT_ATTRIBUTE_SHEET,
        cell=stat.address,
        observed=f"{observed:g}",
    )


def _check_value_set(
    check: DerivedCheck, reports: Mapping[ReportKind, ReportDocument]
) -> CheckOutcome:
    """Assert a distribution's keys obey an allow-list or a deny-list.

    Args:
        check: The derived check.
        reports: The parsed reports.

    Returns:
        The outcome, naming the exact offending members.
    """
    document = reports.get("state_distribution")
    sheet_name, column = STATE_SHEET, "State"
    if check.field_name != "state":
        document = reports.get("field_distribution")
        sheet_name, column = FIELD_SHEET, "Field"
    if document is None:
        return CheckOutcome(
            passed=None, detail=f"The {check.field_name} distribution report was not supplied."
        )

    sheet = document.sheet(sheet_name)
    if sheet is None:
        return CheckOutcome(
            passed=None, detail=f"Sheet {sheet_name!r} was not found in the distribution report."
        )

    present = [str(c.value).strip() for c in sheet.column(column) if c.value is not None]
    allowed = {v.strip().upper() for v in check.values}

    if check.kind == "value_set_excludes":
        offending = sorted({p for p in present if p.upper() in allowed})
        detail = (
            f"The distribution contains excluded value(s): {', '.join(offending)}."
            if offending
            else "No excluded value appears in the distribution."
        )
    else:
        offending = sorted({p for p in present if p.upper() not in allowed})
        detail = (
            f"The distribution contains {', '.join(offending)}, which the OSL does not allow "
            f"(allowed: {', '.join(sorted(allowed))})."
            if offending
            else f"Every value in the distribution is allowed ({', '.join(sorted(allowed))})."
        )

    return CheckOutcome(
        passed=not offending,
        detail=detail,
        report_kind=document.kind,
        sheet=sheet_name,
        observed=", ".join(sorted(set(present))),
    )


def _check_fields_present(
    check: DerivedCheck,
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable | None = None,
) -> CheckOutcome:
    """Assert every requested attribute was delivered.

    Args:
        check: The derived check.
        reports: The parsed reports.
        aliases: The attribute alias table.

    Returns:
        The outcome, naming the missing attributes.
    """
    stats = attribute_stats(reports, aliases)
    if not stats:
        return CheckOutcome(passed=None, detail="The DIRT attribute sheet was not available.")

    resolve = aliases.resolve if aliases is not None else normalize_field_name
    missing = sorted(name for name in check.values if resolve(name) not in stats)
    return CheckOutcome(
        passed=not missing,
        detail=(
            f"The reports are missing {len(missing)} requested attribute(s): {', '.join(missing)}."
            if missing
            else f"All {len(check.values)} requested attributes are present."
        ),
        report_kind="dirt",
        sheet=DIRT_ATTRIBUTE_SHEET,
        observed=f"{len(stats)} attributes present",
    )


def _flow_value(document: ReportDocument, label: str) -> float | None:
    """Read one labelled total from the counts report.

    Args:
        document: The counts report.
        label: The row label, e.g. ``"Accepts"``.

    Returns:
        The number, or ``None`` when the label is absent or not numeric.
    """
    sheet = document.sheet(FLOW_SHEET)
    if sheet is None:
        return None
    header_width = len(sheet.header)
    cell = sheet.lookup(label, value_column=max(header_width - 1, 1))
    return None if cell is None else to_number(cell.value)


def _check_counts_reconcile(reports: Mapping[ReportKind, ReportDocument]) -> CheckOutcome:
    """Assert accepts plus rejects equals the input count.

    Args:
        reports: The parsed reports.

    Returns:
        The outcome, naming the shortfall.
    """
    document = reports.get("counts")
    if document is None:
        return CheckOutcome(passed=None, detail="The counts report was not supplied.")

    accepts = _flow_value(document, "Accepts")
    rejects = _flow_value(document, "Rejects")
    total = _flow_value(document, "Input")
    if accepts is None or rejects is None or total is None:
        return CheckOutcome(
            passed=None,
            detail="The counts report does not carry accepts, rejects, and input totals.",
            report_kind="counts",
            sheet=FLOW_SHEET,
        )

    difference = accepts + rejects - total
    return CheckOutcome(
        passed=difference == 0,
        detail=(
            f"Accepts {accepts:,.0f} plus rejects {rejects:,.0f} is {accepts + rejects:,.0f} "
            f"against an input of {total:,.0f}, a difference of {difference:+,.0f}."
        ),
        report_kind="counts",
        sheet=FLOW_SHEET,
        observed=f"{difference:+,.0f}",
    )


def _check_count_equals(
    check: DerivedCheck, reports: Mapping[ReportKind, ReportDocument]
) -> CheckOutcome:
    """Assert the delivered count equals the quantity the OSL states.

    Args:
        check: The derived check.
        reports: The parsed reports.

    Returns:
        The outcome.
    """
    document = reports.get("counts")
    if document is None:
        return CheckOutcome(passed=None, detail="The counts report was not supplied.")
    accepts = _flow_value(document, "Accepts")
    if accepts is None or check.value is None:
        return CheckOutcome(
            passed=None,
            detail="The counts report does not carry an accepts total.",
            report_kind="counts",
            sheet=FLOW_SHEET,
        )
    return CheckOutcome(
        passed=accepts == check.value,
        detail=f"The delivery contains {accepts:,.0f} records; the OSL states {check.value:,.0f}.",
        report_kind="counts",
        sheet=FLOW_SHEET,
        observed=f"{accepts:,.0f}",
    )
