"""What a delivery calls the fields the tool checks (Phase 6.14b, ADR-041).

The credit date is the date a delivery is cut as of. Reports say so in a cell, and what
that cell is *called* varies with whoever built the workbook: *as-of date*, *data date*,
*cycle date*, *extract date*. Until this existed the check searched every sheet name,
header and cell for the date's **value**, which answers "does this date appear
somewhere" and not "does the date this report is cut as of match the one you gave me".
It could report an absence and never a mismatch, and any coincidental occurrence passed
it.

Resolving the label first turns a presence test into a comparison. Where a labelled cell
is found the two dates are compared and a disagreement is reported with both of them;
where none is found the old search still runs and the finding says that it did, so a
weaker answer never reads like a stronger one.

Labels are scoped data using the one scope vocabulary (ADR-029), so a programme or a
single configuration can name its own spelling. They are deliberately not
``attribute_aliases``: that table resolves *data attribute* names and loads as
global-plus-customer only. Overloading it would repeat the near-miss ADR-029 exists to
prevent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Final, Iterable, Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from greenlight_ai import scopes
from greenlight_ai.db import models
from greenlight_ai.parsers.base import ReportDocument

__all__ = [
    "CANONICAL_FIELDS",
    "CREDIT_DATE",
    "DEFAULT_LABELS",
    "LabelHit",
    "find_labelled_value",
    "normalize_label",
    "resolve_labels",
]

_LOG: Final = logging.getLogger(__name__)

#: The field this names. A closed set, so a typo cannot invent one.
CREDIT_DATE: Final[str] = "credit_date"
CANONICAL_FIELDS: Final[tuple[str, ...]] = (CREDIT_DATE,)

#: What a delivery is seen to call each field, before anybody configures anything.
#: These are the spellings the reports in front of us use; a programme that says it
#: differently adds its own, scoped, rather than editing these.
DEFAULT_LABELS: Final[dict[str, tuple[str, ...]]] = {
    CREDIT_DATE: (
        "credit date",
        "as-of date",
        "as of date",
        "asof date",
        "data date",
        "cycle date",
        "extract date",
        "extract as of",
        "file date",
        "report date",
        "snapshot date",
    ),
}

_PUNCTUATION: Final = re.compile(r"[^\w\s]")
_SEPARATORS: Final = re.compile(r"[\s_]+")


@dataclass(frozen=True, slots=True)
class LabelHit:
    """A labelled cell found in a report.

    Attributes:
        value: The cell's text, verbatim, ready to be compared.
        label: The label that matched, as the report writes it.
        source: Where it was found, in words a person can act on, e.g.
            ``"counts · Summary!As-of date"``.
    """

    value: str
    label: str
    source: str


def normalize_label(value: str) -> str:
    """Reduce a label to a comparable form.

    Args:
        value: A label as configured or as written in a report.

    Returns:
        Lowercased, punctuation removed, runs of space and underscore collapsed to one
        space, so ``As-of Date``, ``as_of date`` and ``As of  Date`` all compare alike.
    """
    text = _PUNCTUATION.sub(" ", value.strip().lower())
    return _SEPARATORS.sub(" ", text).strip()


def resolve_labels(
    session: Session,
    canonical: str,
    customer: str = "",
    programme: str = "",
    configuration_id: str = "",
) -> tuple[str, ...]:
    """The labels in force for one run, most specific scope first.

    Args:
        session: An open session.
        canonical: Which field, from :data:`CANONICAL_FIELDS`.
        customer: The run's customer.
        programme: The run's delivery programme code.
        configuration_id: The run's configuration id.

    Returns:
        The configured labels that cover this run, followed by the built-in ones, with
        duplicates removed. Built-ins come last so a configured label is tried first,
        and are always present so switching the table off never makes the check worse
        than it was before the table existed.
    """
    configured = list(
        session.execute(
            sa.select(models.FieldLabel)
            .where(
                models.FieldLabel.canonical == canonical,
                models.FieldLabel.is_active.is_(True),
            )
            .order_by(models.FieldLabel.id)
        ).scalars()
    )
    in_force = [
        row.label
        for row in configured
        if scopes.covers(row.scope, customer, programme, configuration_id)
    ]
    ordered = list(in_force) + list(DEFAULT_LABELS.get(canonical, ()))
    seen: set[str] = set()
    unique: list[str] = []
    for label in ordered:
        key = normalize_label(label)
        if key and key not in seen:
            seen.add(key)
            unique.append(label)
    return tuple(unique)


def find_labelled_value(
    reports: dict[str, ReportDocument] | Iterable[tuple[str, ReportDocument]],
    labels: Sequence[str],
) -> LabelHit | None:
    """Find the first cell whose label is one of ``labels``, and read its value.

    A labelled value in these workbooks sits beside its label on the same row, so the
    search takes the next non-empty cell after the label. A label in a sheet's header
    row instead describes a column, which is a different shape and is not read here:
    guessing between the two is how a check comes to report the wrong cell confidently.

    Args:
        reports: The parsed reports, keyed by artifact key.
        labels: The labels to look for, most specific first.

    Returns:
        The first hit, or ``None`` when no labelled cell is found anywhere.
    """
    wanted = {normalize_label(label): label for label in labels if normalize_label(label)}
    if not wanted:
        return None

    items = reports.items() if isinstance(reports, dict) else reports
    for key, document in sorted(items, key=lambda pair: pair[0]):
        for sheet in document.sheets:
            for row in sheet.rows:
                cells = list(row)
                for index, cell in enumerate(cells):
                    text = str(cell.value).strip() if cell.value is not None else ""
                    if not text:
                        continue
                    match = wanted.get(normalize_label(text))
                    if match is None:
                        continue
                    for following in cells[index + 1 :]:
                        value = str(following.value).strip() if following.value is not None else ""
                        if value:
                            _LOG.info("found %r in %s · %s, value %r", text, key, sheet.name, value)
                            return LabelHit(
                                value=value,
                                label=text,
                                source=f"{key} · {sheet.name}!{text}",
                            )
    return None
