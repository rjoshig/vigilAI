"""Do the artifacts belong to the delivery the submitter described? (ADR-041)

The tool validates a delivery thoroughly and, until this existed, said nothing about
whether the delivery was the one the submitter claimed. A run submitted with the wrong
customer and the wrong configuration id finished with four ordinary findings and a
confident summary: the evidence was present and parsed — an ETL configuration declares
its own ``configuration_id`` and usually its ``customer`` — and nothing compared either
with what was typed on the form.

This module is the comparison, and it is only the comparison. Every function here is
pure: no model call, no database, no filesystem. The model is never asked whether two
strings are the same thing (ADR-001), and the caller decides what a mismatch means.

A mismatch is deliberately **not** a finding. A finding is something a reviewer weighs
against other findings; a mismatch says the other findings may have been computed
against the wrong premise, so it belongs in front of them rather than among them.

Each comparison returns what was compared, both values and how they were read, so the
screen can show the disagreement rather than a verdict. Three outcomes are distinguished
because they mean different things to the person reading them:

- ``match`` — the same, allowing for case and punctuation.
- ``near`` — the same once the noise is removed, but not written the same way.
  "Acme Card Services" against "ACME Card Services, Inc." is nearly always the same
  customer and occasionally is not, so it is shown and never silently passed.
- ``different`` — not the same.
- ``absent`` — the artifact does not declare it, so there was nothing to compare.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from typing import Final, Iterable, Literal, Sequence

__all__ = [
    "COMPANY_SUFFIXES",
    "MATCH_FIELDS",
    "MatchKind",
    "MatchResult",
    "compare_configuration_id",
    "compare_credit_date",
    "compare_customer",
    "compare_run",
    "disagreements",
    "normalize_company",
    "normalize_identifier",
]

_LOG: Final = logging.getLogger(__name__)

#: What a comparison concluded. ``match`` needs nothing from anybody; the other three
#: are shown to the person before the run starts.
MatchKind = Literal["match", "near", "different", "absent"]

#: The fields compared, in the order they are shown. A closed set: each one is a thing
#: the submitter types and an artifact independently declares.
MATCH_FIELDS: Final[tuple[str, ...]] = ("configuration_id", "customer", "credit_date")

#: Dropped from a company name before comparing. A customer that renames itself from
#: "Acme Card Services" to "Acme Card Services, Inc." has not become a different
#: customer, and a submitter who omits the suffix has not made a mistake worth stopping
#: for — but it is still shown as ``near``, because occasionally it has.
COMPANY_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "llp",
        "ltd",
        "limited",
        "plc",
        "corp",
        "corporation",
        "co",
        "company",
        "na",
        "sa",
        "ag",
        "gmbh",
        "bv",
        "nv",
        "pty",
        "group",
        "holdings",
    }
)

#: Everything that is not a letter, a digit or a space.
_PUNCTUATION: Final = re.compile(r"[^\w\s]")
#: Runs of whitespace and separators.
_SEPARATORS: Final = re.compile(r"[\s\-_]+")


@dataclass(frozen=True, slots=True)
class MatchResult:
    """One comparison of a submitted value against what an artifact declares.

    Attributes:
        field: Which of :data:`MATCH_FIELDS` this is.
        submitted: What the person typed, verbatim. Shown as they wrote it.
        declared: What the artifact says, verbatim, or empty when it says nothing.
        kind: What the comparison concluded.
        source: Where ``declared`` was read from, in words a person can act on, e.g.
            ``"the configuration's 'customer'"``. Empty when nothing was found.
    """

    field: str
    submitted: str
    declared: str
    kind: MatchKind
    source: str = ""

    @property
    def agrees(self) -> bool:
        """Whether this comparison needs nobody's attention.

        Returns:
            True when the values matched, or when the artifact declared nothing to
            compare against. Absence is not disagreement: a configuration that names no
            customer has not contradicted anybody.
        """
        return self.kind in ("match", "absent")


def normalize_identifier(value: str) -> str:
    """Reduce an identifier to a comparable form.

    Args:
        value: A configuration id as typed or as declared.

    Returns:
        Uppercased, with punctuation and separators removed, so ``CFG-GEO-02``,
        ``cfg_geo_02`` and ``CFG GEO 02`` compare alike.
    """
    text = _PUNCTUATION.sub(" ", value.strip().upper())
    return _SEPARATORS.sub("", text)


def normalize_company(value: str) -> str:
    """Reduce a company name to a comparable form.

    Args:
        value: A customer name as typed or as declared.

    Returns:
        Lowercased, punctuation removed, common company suffixes dropped, and remaining
        words joined by a single space. An empty result means the name was nothing but
        suffixes, in which case the original words are kept rather than compared to
        nothing.
    """
    text = _PUNCTUATION.sub(" ", value.strip().lower())
    words = [word for word in _SEPARATORS.split(text) if word]
    kept = [word for word in words if word not in COMPANY_SUFFIXES]
    return " ".join(kept or words)


def _text_result(
    field: str, submitted: str, declared: str, source: str, exact: str, other: str
) -> MatchResult:
    """Build a result from two already-normalised forms.

    Args:
        field: Which field this is.
        submitted: What the person typed, verbatim.
        declared: What the artifact declares, verbatim.
        source: Where the declared value was read from.
        exact: The normalised submitted value.
        other: The normalised declared value.

    Returns:
        The comparison. ``match`` when the verbatim values are equal ignoring
        surrounding space, ``near`` when only the normalised forms are equal, and
        ``different`` otherwise.
    """
    if submitted.strip() == declared.strip():
        kind: MatchKind = "match"
    elif exact == other:
        kind = "near"
    else:
        kind = "different"
    return MatchResult(
        field=field,
        submitted=submitted.strip(),
        declared=declared.strip(),
        kind=kind,
        source=source,
    )


def compare_configuration_id(submitted: str, declared: str) -> MatchResult:
    """Compare the configuration id typed on the form with the one in the file.

    Args:
        submitted: The configuration id the submitter chose.
        declared: The ``configuration_id`` the ETL configuration declares.

    Returns:
        The comparison. A configuration with no id never reaches here — the parser
        refuses it — so ``absent`` means the configuration itself was unreadable.
    """
    if not declared.strip():
        return MatchResult(
            field="configuration_id",
            submitted=submitted.strip(),
            declared="",
            kind="absent",
            source="",
        )
    return _text_result(
        "configuration_id",
        submitted,
        declared,
        "the configuration's 'configuration_id'",
        normalize_identifier(submitted),
        normalize_identifier(declared),
    )


def compare_customer(submitted: str, declared: str) -> MatchResult:
    """Compare the customer chosen on the form with the one the configuration names.

    Args:
        submitted: The customer the submitter chose.
        declared: The ``customer`` the ETL configuration names, or empty.

    Returns:
        The comparison. ``absent`` when the configuration names no customer, which is
        allowed and is not a disagreement.
    """
    if not declared.strip():
        return MatchResult(
            field="customer", submitted=submitted.strip(), declared="", kind="absent", source=""
        )
    return _text_result(
        "customer",
        submitted,
        declared,
        "the configuration's 'customer'",
        normalize_company(submitted),
        normalize_company(declared),
    )


def compare_credit_date(submitted: dt.date | None, declared: str, source: str = "") -> MatchResult:
    """Compare the credit date given on the form with the one read from a report.

    Args:
        submitted: The credit date the submitter gave, or ``None`` when they gave none.
        declared: The date as the artifact writes it, verbatim, or empty when no
            labelled date was found.
        source: Where it was read from, e.g. ``"counts · Summary!As-of date"``.

    Returns:
        The comparison. ``absent`` when either side is missing, because a date nobody
        stated cannot disagree with anything. Values are compared as dates where the
        declared spelling parses and as text where it does not, so an unrecognised
        spelling is reported rather than silently treated as a mismatch.
    """
    if submitted is None or not declared.strip():
        return MatchResult(
            field="credit_date",
            submitted=submitted.isoformat() if submitted else "",
            declared=declared.strip(),
            kind="absent",
            source=source if declared.strip() else "",
        )
    parsed = _parse_spelled_date(declared)
    if parsed is not None:
        kind: MatchKind = "match" if parsed == submitted else "different"
    else:
        kind = "match" if declared.strip() == submitted.isoformat() else "different"
    return MatchResult(
        field="credit_date",
        submitted=submitted.isoformat(),
        declared=declared.strip(),
        kind=kind,
        source=source,
    )


def _parse_spelled_date(value: str) -> dt.date | None:
    """Read a date written in any of the spellings the reports use.

    Args:
        value: The cell's text.

    Returns:
        The date, or ``None`` when the text is not one of the spellings. The formats
        mirror ``pipeline/s7_reports._date_spellings``, which writes the same set out;
        reading and writing them stay together deliberately.
    """
    text = value.strip()
    formats = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y%m%d",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%B %d, %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%d %b %Y",
        "%d-%b-%Y",
    )
    for fmt in formats:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def disagreements(results: Iterable[MatchResult]) -> tuple[MatchResult, ...]:
    """Keep only the comparisons somebody has to look at.

    Args:
        results: Every comparison made for a run.

    Returns:
        Those that did not agree, in the order given. An empty tuple means the run may
        start without anybody being asked anything.
    """
    return tuple(result for result in results if not result.agrees)


def compare_run(
    submitted_configuration_id: str,
    submitted_customer: str,
    submitted_credit_date: dt.date | None,
    declared_configuration_id: str,
    declared_customer: str,
    declared_credit_date: str = "",
    credit_date_source: str = "",
) -> tuple[MatchResult, ...]:
    """Compare every field of one submission against its artifacts.

    Args:
        submitted_configuration_id: The configuration id typed on the form.
        submitted_customer: The customer chosen on the form.
        submitted_credit_date: The credit date given on the form, if any.
        declared_configuration_id: What the configuration declares.
        declared_customer: The customer the configuration names, if any.
        declared_credit_date: A labelled date read from a report, if one was found.
        credit_date_source: Where that date was read from.

    Returns:
        One result per field of :data:`MATCH_FIELDS`, in that order, agreeing or not.
    """
    results = (
        compare_configuration_id(submitted_configuration_id, declared_configuration_id),
        compare_customer(submitted_customer, declared_customer),
        compare_credit_date(submitted_credit_date, declared_credit_date, credit_date_source),
    )
    unhappy: Sequence[MatchResult] = disagreements(results)
    if unhappy:
        _LOG.info(
            "artifact match: %d of %d fields disagree (%s)",
            len(unhappy),
            len(results),
            ", ".join(f"{r.field}={r.kind}" for r in unhappy),
        )
    return results
