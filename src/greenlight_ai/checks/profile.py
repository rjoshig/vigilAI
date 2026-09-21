"""What a delivery's attributes looked like, as numbers (Phase 6.21c).

Every finding this product made before Phase 6.21c traced back to a rule somebody
authored. That is the right default — a finding nobody can explain is a finding nobody
acts on — but it means the tool could only ever find what it had been told to look for.
``docs/design.md`` has promised a ``profile_anomaly`` finding since Phase 2 (*"unexpected
nulls, wrong type, mean far from prior runs"*); the type was declared, labelled in the
UI, used in a prompt example, and **produced nowhere**.

Producing one needs a baseline, and the only honest baseline is the delivery's own
history. So each finalized run stores the shape of what it delivered — per attribute, a
null rate, a minimum, a maximum and a mean — and a later run of the same configuration
is compared against them.

**These are aggregates and nothing else** (ADR-003). A null *rate*, not which rows were
null; a minimum, not the record that held it. That is what makes them safe to store for
the retention window and safe to show the model in
:mod:`greenlight_ai.checks.anomaly`'s second half.
"""

from __future__ import annotations

import logging
from typing import Final, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from greenlight_ai.checks.named_values import to_number
from greenlight_ai.checks.reports import DIRT_ATTRIBUTE_SHEET, column_for, sheet_for
from greenlight_ai.parsers.base import ReportDocument, ReportKind
from greenlight_ai.resolve.layout import LayoutResolver
from greenlight_ai.rules.normalize import AliasTable, normalize_field_name

__all__ = ["MEASURES", "AttributeProfile", "measure_of", "read_profile"]

_LOG: Final = logging.getLogger(__name__)

#: The measures a profile carries, in the order a finding names them. Each is a single
#: number per attribute per delivery, which is what makes a history of them comparable.
MEASURES: Final[tuple[str, ...]] = ("null_rate", "minimum", "maximum", "mean")

#: What each measure is called in a sentence a reviewer reads.
MEASURE_LABEL: Final[dict[str, str]] = {
    "null_rate": "null rate",
    "minimum": "minimum",
    "maximum": "maximum",
    "mean": "mean",
}

#: The column headings each measure is read from. Resolved up the ladder like every
#: other name (Phase 6.21a), so a report heading its null column ``Null %`` is read.
_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "null_rate": ("Nulls", "Null %"),
    "minimum": ("Min",),
    "maximum": ("Max",),
    "mean": ("Mean",),
}


class AttributeProfile(BaseModel):
    """The shape of one delivered attribute.

    Attributes:
        name: The attribute as the report writes it.
        null_rate: The share of delivered records with no value, ``0.0``–``1.0``.
        minimum: The smallest value delivered, when numeric.
        maximum: The largest, when numeric.
        mean: The average, when numeric.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    null_rate: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None


def measure_of(profile: AttributeProfile, measure: str) -> float | None:
    """Read one measure off a profile by name.

    Args:
        profile: The attribute's profile.
        measure: One of :data:`MEASURES`.

    Returns:
        The value, or ``None`` when this delivery did not report it.
    """
    value = getattr(profile, measure, None)
    return float(value) if isinstance(value, (int, float)) else None


def _rate(raw: object) -> float | None:
    """Read a null column, whether it holds a count, a share or a percentage.

    Args:
        raw: The cell's value.

    Returns:
        A share between 0 and 1, or ``None``. A number above 1 is read as a
        percentage, because a "null rate" of 18 means 18% in every report anyone has
        shown us and a rate of 1800% is not a thing. A count of nulls cannot be turned
        into a rate without a row count, so a whole number above 100 is left alone
        rather than guessed at.
    """
    number = to_number(raw)
    if number is None or number < 0:
        return None
    if number <= 1:
        return number
    if number <= 100:
        return number / 100.0
    return None


def read_profile(
    reports: Mapping[ReportKind, ReportDocument],
    aliases: AliasTable | None = None,
    resolver: LayoutResolver | None = None,
) -> dict[str, AttributeProfile]:
    """Read the shape of every attribute out of the DIRT.

    Args:
        reports: The parsed reports.
        aliases: The attribute alias table, so an attribute is stored under the name
            a later run will look for it by.
        resolver: The run's layout resolver, so a drifted heading is still read.

    Returns:
        Canonical attribute name to its profile, empty when the DIRT is absent or
        carries no attribute sheet. Empty is not an error: a delivery with no DIRT has
        no shape to compare, and the caller says so rather than inventing one.
    """
    canonical = aliases.resolve if aliases is not None else normalize_field_name
    dirt = reports.get("dirt")
    if dirt is None:
        return {}
    sheet = sheet_for(dirt, DIRT_ATTRIBUTE_SHEET, resolver)
    if sheet is None:
        return {}

    name_index = column_for(sheet, "Attribute", resolver, "dirt")
    if name_index is None:
        return {}

    columns: dict[str, int | None] = {}
    for measure, headings in _COLUMNS.items():
        found: int | None = None
        for heading in headings:
            found = column_for(sheet, heading, resolver, "dirt")
            if found is not None:
                break
        columns[measure] = found

    def cell(row: Sequence[object], measure: str) -> object:
        index = columns[measure]
        if index is None or index >= len(row):
            return None
        return getattr(row[index], "value", None)

    profiles: dict[str, AttributeProfile] = {}
    for row in sheet.rows:
        if name_index >= len(row) or row[name_index].value is None:
            continue
        name = str(row[name_index].value).strip()
        if not name:
            continue
        profiles[canonical(name)] = AttributeProfile(
            name=name,
            null_rate=_rate(cell(row, "null_rate")),
            minimum=to_number(cell(row, "minimum")),
            maximum=to_number(cell(row, "maximum")),
            mean=to_number(cell(row, "mean")),
        )

    _LOG.info("profiled %d attributes from the DIRT", len(profiles))
    return profiles
