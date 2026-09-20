"""The programme keyword check, measured for brittleness (Phase 6.17a).

The same half-hour measurement `docs/phase-6.15.md` ran against compliance rules and
`docs/phase-6.16.md` ran against named values, run against the third surface that had
never had it: the programme classification check in `s7_reports._check_programme`.

**These tests assert what the check does today, not what it should do.** They are the
measurement of record, so the result cannot drift unnoticed and a future fix has to
come past them deliberately. Every case in the first two classes is genuinely the
programme it declares; a finding on one of those is a false positive.

The measured table is in `docs/phase-6.17.md`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from greenlight_ai.db.catalog import DEFAULT_SCOPES
from greenlight_ai.parsers.base import ConfigDocument, OslDocument, OslSection
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import RunGuidance
from greenlight_ai.pipeline.s7_reports import _check_programme

#: The shipped programmes, exactly as `seed_defaults` loads them. The measurement uses
#: the seeded words rather than invented ones, because the seeded words are what a
#: customer meets on their first run.
SEEDED = {scope.code: tuple(scope.keywords) for scope in DEFAULT_SCOPES if scope.keywords}


def _build(cls: Any, **given: Any) -> Any:
    """Construct a parser dataclass with harmless defaults for whatever is not given."""
    values: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name in given:
            values[field.name] = given[field.name]
        elif (
            field.default is not dataclasses.MISSING
            or field.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        ):
            continue
        elif field.type in ("str", str):
            values[field.name] = ""
        elif field.type in ("int", int):
            values[field.name] = 1
        elif "Path" in str(field.type):
            values[field.name] = Path("x")
        else:
            values[field.name] = ()
    return cls(**values)


def measure(osl_text: str, declared: str) -> str:
    """Run the check over one OSL wording and report what fired.

    Args:
        osl_text: The OSL's text, as one section.
        declared: The programme code the submitter declared.

    Returns:
        ``"silent"`` when nothing fired, otherwise the finding's severity.
    """
    context = RunContext(
        run_id="measure",
        osl_path=Path("x.docx"),
        config_path=Path("x.json"),
        report_paths={},
        client=None,  # type: ignore[arg-type]
        guidance=RunGuidance(
            scope_code=declared,
            scope_label=declared,
            programme_keywords=SEEDED,
        ),
    )
    section = _build(OslSection, number="1", heading="Scope", level=1, paragraphs=(osl_text,))
    context.osl = _build(OslDocument, sections=(section,))
    context.config = _build(ConfigDocument, blocks=())
    _check_programme(context)
    return "silent" if not context.findings else context.findings[0].severity


# --- class 1: the same programme, worded the way the keywords expect ----------------


@pytest.mark.parametrize(
    "declared,osl_text",
    [
        ("AS", "This prescreen campaign delivers a firm offer of credit to consumers."),
        ("AS", "The prescreened population receives solicitations under the Act."),
        ("AM", "Account monitoring of the existing accounts, as a portfolio review."),
        ("ARCHIVE", "An archival snapshot of historical records for the retention window."),
        ("ARCHIVE", "Records are archived and the archives are delivered quarterly."),
    ],
)
def test_where_the_words_match_the_check_is_silent_and_free(declared: str, osl_text: str) -> None:
    """The check is not broken. Substring matching catches inflections for free.

    ``prescreened`` contains ``prescreen`` and ``archives`` contains ``archive``, so a
    single-word keyword survives most of what English does to it. This class is why the
    check is worth keeping rather than replacing.
    """
    assert measure(osl_text, declared) == "silent"


# --- class 2: the same programme, worded the way another customer might -------------


@pytest.mark.parametrize(
    "declared,osl_text,fires",
    [
        # A phrase keyword needs exact adjacency: a hyphen breaks it.
        ("AS", "An invitation-to-apply mailing for non-customers, scored and filtered.", "review"),
        # Plain business vocabulary for the same campaign.
        (
            "AS",
            "A promotional acquisition campaign targeting non-customers with a credit "
            "product mailing, filtered to the marketing universe.",
            "review",
        ),
        # The abbreviation the business actually says out loud.
        ("AS", "The ITA file is built monthly and delivered to the mail house.", "review"),
        # The two halves of two different phrase keywords, recombined.
        ("AM", "Portfolio monitoring of the book, run monthly across every open trade.", "review"),
        # Singular where the keyword is plural: `existing accounts` is not a substring.
        ("AM", "Each existing account is rescored monthly and returned with its band.", "review"),
        ("AM", "An ongoing review of the portfolio, refreshing scores on open trades.", "review"),
        ("AM", "A monthly account management refresh across the open book.", "review"),
        ("ARCHIVE", "A back-file extract of prior-year records, frozen at period end.", "review"),
        ("ARCHIVE", "A legacy history pull covering closed trades from earlier periods.", "review"),
    ],
)
def test_the_same_programme_in_other_words_fires(declared: str, osl_text: str, fires: str) -> None:
    """Every one of these IS the declared programme, and every one produces a finding.

    The failure shape is the same one 6.15 measured: a presence test cannot tell
    *absent* from *spelled differently*. Phrase keywords are the fragile ones — they
    need exact adjacency and exact plurality.
    """
    assert measure(osl_text, declared) == fires


# --- class 3: where it escalates to high, and why that is the sharp one -------------


def test_one_reworded_phrase_flips_a_realistic_osl_from_silent_to_high() -> None:
    """The knife edge. One hit anywhere silences the check; zero hits can mean HIGH.

    This is a realistic prescreen OSL: purpose, universe, delivery, compliance. It is
    silent only because its last sentence happens to say `firm offer`. Reword that one
    phrase — leaving a document that is still plainly a solicitation — and the check
    reports at the highest severity it has that the delivery is a different programme.
    """
    osl = (
        "Purpose. A promotional acquisition campaign for non-customers. "
        "Universe. Consumers scored above the cut, excluding existing accounts and "
        "anyone on the opt-out list. An account review removes current relationships. "
        "Delivery. A monthly file to the mail house, with counts by state. "
        "Compliance. Delivered under the {phrase} provisions of the Act."
    )
    assert measure(osl.format(phrase="firm offer"), "AS") == "silent"
    assert measure(osl.format(phrase="applicable"), "AS") == "high"


@pytest.mark.parametrize(
    "declared,osl_text",
    [
        (
            "AS",
            "A promotional acquisition mailing. The universe is a snapshot as at month "
            "end, with historical performance attached for scoring.",
        ),
        (
            "AM",
            "An ongoing refresh of the open book. Each delivery is a snapshot, with "
            "historical balances for trend.",
        ),
        (
            "ARCHIVE",
            "A back-file pull. Covers existing accounts closed in prior years; an "
            "account review determines what is in range.",
        ),
    ],
)
def test_generic_words_borrowed_from_another_programme_escalate_to_high(
    declared: str, osl_text: str
) -> None:
    """The second defect, which compounds the first.

    Severity is `high` when another programme clears the two-hit floor. Two of the
    Archives keywords — `snapshot` and `historical` — are ordinary data-delivery
    vocabulary that appears in specifications for every programme. So a document whose
    own words were missed does not merely raise a review item: it is confidently
    reported as a different programme, on the strength of two words that carry no
    programme meaning at all.
    """
    assert measure(osl_text, declared) == "high"


# --- class 4: the control, which matters as much as the rest ------------------------


@pytest.mark.parametrize(
    "declared,osl_text",
    [
        ("AS", "Account monitoring of the existing accounts; a portfolio review monthly."),
        ("AM", "A prescreen campaign delivering a firm offer to the solicitation universe."),
        ("ARCHIVE", "A prescreen file: firm offer, invitation to apply, solicitation universe."),
    ],
)
def test_a_genuinely_wrong_declaration_is_still_caught(declared: str, osl_text: str) -> None:
    """Whatever is built next must not lose this.

    These deliveries really are declared as the wrong programme, and the check reports
    every one at high severity. That is the behaviour the check exists for.
    """
    assert measure(osl_text, declared) == "high"
