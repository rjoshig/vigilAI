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
from typing import Final, Mapping, Sequence

from greenlight_ai.checks.named_values import to_number
from greenlight_ai.parsers.base import ReportCell, ReportDocument, ReportKind, ReportSheet
from greenlight_ai.resolve import attributes as attribute_match
from greenlight_ai.resolve.layout import LayoutResolver
from greenlight_ai.rules.derive import DerivedCheck
from greenlight_ai.rules.normalize import AliasTable, normalize_field_name

__all__ = [
    "CheckOutcome",
    "run_derived_check",
    "attribute_stats",
    "AttributeStat",
    "REPORT_CHECKED_KINDS",
    "WHAT",
    "sheet_for",
    "column_for",
    "label_for",
    "waterfall_rows",
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
        "unknown_product_code",
        "counts_reconcile",
        "count_equals",
    }
)


#: What each name the fixed checks look for is *for*, in one line. The model rung sees
#: names and nothing else (ADR-003), so this sentence is the only account it gets of
#: what it is being asked to find — and a name without one would be a guess invited.
WHAT: Final[dict[str, str]] = {
    DIRT_ATTRIBUTE_SHEET: (
        f"a worksheet called {DIRT_ATTRIBUTE_SHEET!r} — the sheet listing each delivered "
        "field with its statistics, one row per field"
    ),
    STATE_SHEET: (
        f"a worksheet called {STATE_SHEET!r} — the sheet breaking the delivery down by "
        "state or geography"
    ),
    FIELD_SHEET: (
        f"a worksheet called {FIELD_SHEET!r} — the sheet breaking a field down by the "
        "values it took"
    ),
    FLOW_SHEET: (
        f"a worksheet called {FLOW_SHEET!r} — the sheet showing how many records entered "
        "the process, how many each step removed, and how many came out"
    ),
    "Attribute": "a column heading naming the delivered field each row is about",
    "Min": "a column heading holding the smallest value a field took",
    "Max": "a column heading holding the largest value a field took",
    "State": "a column heading holding the state or geography each row is about",
    "Field": "a column heading holding the field value each row is about",
    "Accepts": "a row label for the count of records that passed every filter",
    "Rejects": "a row label for the count of records that were filtered out",
    "Input": "a row label for the count of records that entered the process",
}


def sheet_for(
    document: ReportDocument,
    wanted: str,
    resolver: LayoutResolver | None,
) -> ReportSheet | None:
    """The sheet ``wanted`` names, up the ladder (Phase 6.21a).

    Args:
        document: The parsed report.
        wanted: The sheet name the fixed check looks for.
        resolver: The run's resolver, or ``None`` to stop at the deterministic rungs.

    Returns:
        The sheet, or ``None`` when no rung settled it. ``None`` still becomes a "could
        not evaluate" finding: the ladder widens what counts as found, it never invents
        one.
    """
    if resolver is None:
        return document.sheet(wanted)
    found = resolver.name(
        wanted,
        document.sheet_names,
        kind="sheet",
        artifact=str(document.kind),
        description=WHAT.get(wanted, ""),
    )
    return None if found is None else document.named(found.value)


def column_for(
    sheet: ReportSheet,
    wanted: str,
    resolver: LayoutResolver | None,
    artifact: str = "",
    alternates: Sequence[str] = (),
) -> int | None:
    """The index of the column ``wanted`` names, up the ladder.

    Args:
        sheet: The worksheet.
        wanted: The heading the fixed check looks for.
        resolver: The run's resolver, or ``None``.
        artifact: Which report, for the finding's wording.
        alternates: Other headings that also mean this one, from a caller that knows
            some. The resolver's dictionary supplies any it knows besides
            (Phase 6.22d).

    Returns:
        The zero-based index, or ``None`` when no rung settled it.
    """
    # ``resolve_column``'s ``alternates`` has existed since 6.21a and nothing has ever
    # filled it on this path. The dictionary fills it now (Phase 6.22d): it holds other
    # names for *any* name, and offering them at rung 4 costs nothing when it knows
    # none — which is every name on a deployment with an empty dictionary, and every
    # structural name on any deployment.
    known = () if resolver is None else resolver.dictionary.alternates(wanted, artifact)
    found = (
        sheet.resolve_column(wanted, alternates)
        if resolver is None
        else resolver.name(
            wanted,
            sheet.header,
            kind="column",
            artifact=artifact,
            description=WHAT.get(wanted, ""),
        )
        or sheet.resolve_column(wanted, tuple(alternates) + tuple(known))
    )
    return None if found is None else list(sheet.header).index(found.value)


def label_for(
    sheet: ReportSheet,
    wanted: str,
    resolver: LayoutResolver | None,
    artifact: str = "",
) -> str | None:
    """The label ``wanted`` names, as the workbook spells it, up the ladder.

    Args:
        sheet: The worksheet.
        wanted: The row label the fixed check looks for.
        resolver: The run's resolver, or ``None``.
        artifact: Which report, for the finding's wording.

    Returns:
        The label verbatim, or ``None`` when no rung settled it.
    """
    found = (
        sheet.resolve_label(wanted)
        if resolver is None
        else resolver.name(
            wanted,
            sheet.labels(),
            kind="label",
            artifact=artifact,
            description=WHAT.get(wanted, ""),
        )
    )
    return None if found is None else found.value


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
        unresolved: Attributes the check could not locate in the report although
            something there resembles them (Phase 6.22a). Typed rather than folded into
            ``detail``, because stage 7 raises a review record from it and a caller
            reading it out of a sentence is how the two states got conflated before.
    """

    passed: bool | None
    detail: str
    report_kind: ReportKind | None = None
    sheet: str = ""
    cell: str = ""
    observed: str = ""
    unresolved: tuple[str, ...] = ()


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
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable | None = None,
    resolver: LayoutResolver | None = None,
) -> dict[str, AttributeStat]:
    """Read the per-attribute statistics out of the DIRT.

    Args:
        reports: The parsed reports.
        aliases: The attribute alias table. The DIRT names a column ``SCORE_V3`` where
            the OSL says "score"; without resolving both sides the check cannot find
            the attribute it is meant to assert on.
        resolver: The run's layout resolver (Phase 6.21a). ``None`` stops at the
            deterministic rungs, which is what every caller did before it existed.

    Returns:
        Canonical attribute name to its statistics, empty when the DIRT is absent.
    """
    resolve = aliases.resolve if aliases is not None else normalize_field_name
    dirt = reports.get("dirt")
    if dirt is None:
        return {}
    sheet = sheet_for(dirt, DIRT_ATTRIBUTE_SHEET, resolver)
    if sheet is None:
        return {}

    name_index = column_for(sheet, "Attribute", resolver, "dirt")
    if name_index is None:
        return {}
    min_index = column_for(sheet, "Min", resolver, "dirt")
    max_index = column_for(sheet, "Max", resolver, "dirt")

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


def waterfall_rows(
    reports: Mapping[ReportKind, ReportDocument],
    resolver: LayoutResolver | None = None,
) -> list[dict[str, object]]:
    """Read the counts report's step-by-step flow (Phase 6.21f).

    The frozen report has had a Waterfall section since Phase 5 and
    ``report/render.py`` passed it an empty list, so it has never once been drawn. It
    could not be filled there: by the time a report is rendered the workbooks are long
    parsed and gone, so the flow has to be read while they are open and stored with the
    run, which is what this is for.

    Args:
        reports: The parsed reports.
        resolver: The run's layout resolver, so a drifted sheet is still read.

    Returns:
        One entry per step, in the order the report lists them, each with the step's
        name, the three counts, and whether the arithmetic holds. Empty when the counts
        report is absent or its flow sheet cannot be found — the checks that care say
        so in their own findings, and this does not duplicate them.
    """
    document = reports.get("counts")
    if document is None:
        return []
    sheet = sheet_for(document, FLOW_SHEET, resolver)
    if sheet is None:
        return []

    step_at = column_for(sheet, "Step", resolver, "counts")
    into = column_for(sheet, "Records in", resolver, "counts")
    removed_at = column_for(sheet, "Removed", resolver, "counts")
    out_at = column_for(sheet, "Records out", resolver, "counts")
    if step_at is None or out_at is None:
        return []

    def number(row: Sequence[ReportCell], index: int | None) -> float | None:
        if index is None or index >= len(row):
            return None
        return to_number(row[index].value)

    rows: list[dict[str, object]] = []
    for row in sheet.rows:
        if step_at >= len(row) or row[step_at].value is None:
            continue
        name = str(row[step_at].value).strip()
        records_in = number(row, into)
        removed = number(row, removed_at)
        records_out = number(row, out_at)
        if not name or records_out is None:
            continue
        # A step is broken when its own arithmetic does not hold: what went in, less
        # what it removed, is not what came out. The total rows at the foot of a flow
        # sheet carry no "in" figure and so are never broken by this test — the counts
        # reconciliation check owns those, and two findings for one fact is worse than
        # one (ADR-001: code decides, and it decides once).
        broken = (
            records_in is not None
            and removed is not None
            and abs((records_in - removed) - records_out) > 0.5
        )
        rows.append(
            {
                "step": name,
                "records_in": f"{records_in:,.0f}" if records_in is not None else "—",
                "removed": f"{removed:,.0f}" if removed is not None else "—",
                "records_out": f"{records_out:,.0f}",
                "broken": broken,
            }
        )
    return rows


def run_derived_check(
    check: DerivedCheck,
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable | None = None,
    resolver: LayoutResolver | None = None,
) -> CheckOutcome:
    """Run one derived check against the reports.

    Args:
        check: What the rule implies the reports must show.
        reports: The parsed reports.
        aliases: The attribute alias table, used to match the OSL's wording against the
            report's column names.
        resolver: The run's layout resolver (Phase 6.21a). ``None`` stops at the
            deterministic rungs, which is what every caller did before it existed.

    Returns:
        The outcome. ``passed`` is ``None`` when the report the check needs is absent,
        which becomes a ``could_not_evaluate`` finding. Callers filter on
        :data:`REPORT_CHECKED_KINDS` first, so a non-report kind never reaches here.
    """
    if check.kind in ("min_at_least", "min_greater_than", "max_at_most", "max_less_than"):
        return _check_bound(check, reports, aliases, resolver)
    if check.kind in ("value_set_subset", "value_set_excludes"):
        return _check_value_set(check, reports, resolver)
    if check.kind == "fields_present":
        return _check_fields_present(check, reports, aliases, resolver)
    if check.kind == "unknown_product_code":
        return _check_unknown_product_code(check)
    if check.kind == "counts_reconcile":
        return _check_counts_reconcile(reports, resolver)
    if check.kind == "count_equals":
        return _check_count_equals(check, reports, resolver)
    return CheckOutcome(passed=None, detail=f"No report check implements {check.kind!r}.")


def _check_bound(
    check: DerivedCheck,
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable | None = None,
    resolver: LayoutResolver | None = None,
) -> CheckOutcome:
    """Assert a delivered minimum or maximum respects the rule's bound.

    Args:
        check: The derived check.
        reports: The parsed reports.
        aliases: The attribute alias table.
        resolver: The layout resolver, for the sheet and column names.

    Returns:
        The outcome.
    """
    stats = attribute_stats(reports, aliases, resolver)
    if not stats:
        return CheckOutcome(passed=None, detail="The DIRT attribute sheet was not available.")

    canonical = aliases.resolve if aliases is not None else normalize_field_name
    by_spelling = {stat.name: stat for stat in stats.values()}
    match = attribute_match.present(
        check.field_name,
        tuple(by_spelling),
        canonical=canonical,
        resolver=resolver,
        artifact="dirt",
    )
    stat = by_spelling.get(match.found or "")
    if stat is None:
        # Unchanged behaviour — this path was always honest about not knowing. It goes
        # through the shared helper so that tolerance added here reaches the other two
        # callers, which is how the three copies drifted apart in the first place.
        return CheckOutcome(
            passed=None,
            detail=f"{check.field_name} does not appear in the DIRT attribute sheet.",
            report_kind="dirt",
            sheet=DIRT_ATTRIBUTE_SHEET,
            unresolved=(check.field_name,) if match.plausible else (),
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
    check: DerivedCheck,
    reports: Mapping[ReportKind, ReportDocument],
    resolver: LayoutResolver | None = None,
) -> CheckOutcome:
    """Assert a distribution's keys obey an allow-list or a deny-list.

    Args:
        check: The derived check.
        reports: The parsed reports.
        resolver: The run's layout resolver (Phase 6.21a). ``None`` stops at the
            deterministic rungs, which is what every caller did before it existed.

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

    sheet = sheet_for(document, sheet_name, resolver)
    if sheet is None:
        return CheckOutcome(
            passed=None, detail=f"Sheet {sheet_name!r} was not found in the distribution report."
        )

    index = column_for(sheet, column, resolver, str(document.kind))
    if index is None:
        return CheckOutcome(
            passed=None,
            detail=f"Column {column!r} was not found in sheet {sheet.name!r}.",
            report_kind=document.kind,
            sheet=sheet.name,
        )
    cells = tuple(row[index] for row in sheet.rows if index < len(row))
    present = [str(c.value).strip() for c in cells if c.value is not None]
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
    resolver: LayoutResolver | None = None,
) -> CheckOutcome:
    """Assert every requested attribute was delivered.

    Two states used to share one answer here: an attribute the delivery does not carry,
    and an attribute whose name in the DIRT we could not work out. Both produced
    ``passed=False`` and a high-severity violation, so a correct delivery that spells
    ``AT01`` as ``debsc_burs_atyrt_at01_1`` was reported as missing an attribute it had
    in fact delivered (Phase 6.22a). They are told apart by evidence now, and an
    attribute that is genuinely absent is still a violation.

    Args:
        check: The derived check.
        reports: The parsed reports.
        aliases: The attribute alias table.
        resolver: The layout resolver, for the sheet and column names.

    Returns:
        The outcome, naming the missing attributes and carrying the unresolved ones
        separately.
    """
    stats = attribute_stats(reports, aliases, resolver)
    if not stats:
        return CheckOutcome(passed=None, detail="The DIRT attribute sheet was not available.")

    canonical = aliases.resolve if aliases is not None else normalize_field_name
    spellings = tuple(stat.name for stat in stats.values())

    missing: list[str] = []
    unresolved: list[str] = []
    for name in check.values:
        match = attribute_match.present(
            name, spellings, canonical=canonical, resolver=resolver, artifact="dirt"
        )
        if match.resolved:
            continue
        (unresolved if match.plausible else missing).append(name)

    missing.sort()
    unresolved.sort()
    parts: list[str] = []
    if missing:
        parts.append(
            f"The reports are missing {len(missing)} requested attribute(s): "
            f"{', '.join(missing)}."
        )
    if unresolved:
        parts.append(
            f"Could not tell what the DIRT calls {len(unresolved)} requested "
            f"attribute(s): {', '.join(unresolved)}. The delivery may well carry them "
            "under another spelling, so this is not counted as missing."
        )
    if not parts:
        parts.append(f"All {len(check.values)} requested attributes are present.")

    return CheckOutcome(
        # A name nobody could resolve is not a failure. It is only a pass once every
        # requested attribute has actually been found.
        passed=False if missing else (None if unresolved else True),
        detail=" ".join(parts),
        report_kind="dirt",
        sheet=DIRT_ATTRIBUTE_SHEET,
        observed=f"{len(stats)} attributes present",
        unresolved=tuple(unresolved),
    )


def _check_unknown_product_code(check: DerivedCheck) -> CheckOutcome:
    """Report that a requirement names a product code nobody defined (Phase 6.22c).

    This never reads a report. It exists because the alternative — expanding an unknown
    code to an empty attribute list — turns "check everything in ABC" into "check
    nothing", and a delivery then passes for the worst possible reason: the tool could
    not say what was asked for.

    It fails rather than degrading to "could not evaluate", and the difference is
    deliberate. The tool knows exactly what is wrong and exactly who fixes it: the
    catalogue is missing a code the OSL names, and an administrator adds it. That is a
    defect in the setup, not an unanswered question about the delivery.

    Args:
        check: The derived check, whose ``field_name`` carries the code.

    Returns:
        The outcome, always failed, naming the code.
    """
    code = check.field_name
    return CheckOutcome(
        passed=False,
        detail=(
            f"The OSL asks for the attributes of product code {code!r}, and the "
            "catalogue does not define it. Nothing was checked against that code: an "
            "undefined code expands to no attributes, which would let the delivery "
            "pass without any of them being looked for. Add the code in the admin "
            "console, then re-check."
        ),
        observed=f"product code {code} is not defined",
    )


def _flow_value(
    document: ReportDocument, label: str, resolver: LayoutResolver | None = None
) -> float | None:
    """Read one labelled total from the counts report.

    Args:
        document: The counts report.
        label: The row label, e.g. ``"Accepts"``.

    Returns:
        The number, or ``None`` when the label is absent or not numeric.
    """
    sheet = sheet_for(document, FLOW_SHEET, resolver)
    if sheet is None:
        return None
    header_width = len(sheet.header)
    spelled = label_for(sheet, label, resolver, str(document.kind))
    if spelled is None:
        return None
    cell = sheet.lookup(spelled, value_column=max(header_width - 1, 1))
    return None if cell is None else to_number(cell.value)


def _check_counts_reconcile(
    reports: Mapping[ReportKind, ReportDocument],
    resolver: LayoutResolver | None = None,
) -> CheckOutcome:
    """Assert accepts plus rejects equals the input count.

    Args:
        reports: The parsed reports.
        resolver: The run's layout resolver (Phase 6.21a). ``None`` stops at the
            deterministic rungs, which is what every caller did before it existed.

    Returns:
        The outcome, naming the shortfall.
    """
    document = reports.get("counts")
    if document is None:
        return CheckOutcome(passed=None, detail="The counts report was not supplied.")

    accepts = _flow_value(document, "Accepts", resolver)
    rejects = _flow_value(document, "Rejects", resolver)
    total = _flow_value(document, "Input", resolver)
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
    check: DerivedCheck,
    reports: Mapping[ReportKind, ReportDocument],
    resolver: LayoutResolver | None = None,
) -> CheckOutcome:
    """Assert the delivered count equals the quantity the OSL states.

    Args:
        check: The derived check.
        reports: The parsed reports.
        resolver: The run's layout resolver (Phase 6.21a). ``None`` stops at the
            deterministic rungs, which is what every caller did before it existed.

    Returns:
        The outcome.
    """
    document = reports.get("counts")
    if document is None:
        return CheckOutcome(passed=None, detail="The counts report was not supplied.")
    accepts = _flow_value(document, "Accepts", resolver)
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
