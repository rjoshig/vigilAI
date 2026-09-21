"""The programme keyword check, measured and then repaired (Phase 6.17a).

The same half-hour measurement `docs/phase-6.15.md` ran against compliance rules and
`docs/phase-6.16.md` ran against named values, run against the third surface that had
never had it: the programme classification check in `s7_reports._check_programme`.

**These are the measured cases, and they now assert the repaired behaviour.** Every
case in the first three classes is genuinely the programme it declares, so a finding on
one of those is a false positive. Across the twenty of them the repair moved the count
from 4 silent / 11 review / **5 high** to 15 silent / 4 review / **1 high**, with the
control class unchanged at 3 of 3.

Two changes did it, and neither asks a model anything:

- `checks/programme_match.py` widens the match so a hyphen, a plural and a word order
  no longer hide a keyword that is present.
- The shipped keyword lists lost the two words that meant nothing — ``snapshot`` and
  ``historical`` — and a programme is now named only on words it alone claims.

The one case still at high severity is kept deliberately, at the foot of this file. It
is a vocabulary problem rather than a spelling one, and it is what
`docs/phase-6.18.md` 6.18f exists to close.

The measured tables are in `docs/phase-6.17.md`.
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
    """Run the check over one OSL wording, against the shipped programmes.

    Args:
        osl_text: The OSL's text, as one section.
        declared: The programme code the submitter declared.

    Returns:
        ``"silent"`` when nothing fired, otherwise the finding's severity.
    """
    return _measure_with(osl_text, declared, SEEDED)


def _measure_with(osl_text: str, declared: str, keywords: dict[str, tuple[str, ...]]) -> str:
    """Run the check over one OSL wording against a given set of programmes.

    Args:
        osl_text: The OSL's text, as one section.
        declared: The programme code the submitter declared.
        keywords: Every programme's keywords, for the cases that are about the rule
            rather than about the shipped list.

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
            programme_keywords=keywords,
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
    "declared,osl_text",
    [
        # A hyphen no longer breaks a phrase keyword.
        ("AS", "An invitation-to-apply mailing for non-customers, scored and filtered."),
        # Plain business vocabulary, now in the shipped list because it is what the
        # business says.
        (
            "AS",
            "A promotional acquisition campaign targeting non-customers with a credit "
            "product mailing, filtered to the marketing universe.",
        ),
        # The two halves of two different phrase keywords, recombined.
        ("AM", "Portfolio monitoring of the book, run monthly across every open trade."),
        # Singular where the keyword is plural.
        ("AM", "Each existing account is rescored monthly and returned with its band."),
        # The keyword's words, in the other order, with connectives between them.
        ("AM", "An ongoing review of the portfolio, refreshing scores on open trades."),
        ("AM", "A monthly account management refresh across the open book."),
        ("ARCHIVE", "A back-file extract of prior-year records, frozen at period end."),
    ],
)
def test_the_same_programme_in_other_words_is_now_silent(declared: str, osl_text: str) -> None:
    """Every one of these IS the declared programme, and every one used to fire.

    Each was a review item before 6.17a. The repair is entirely deterministic: the
    words were always there, and the check could not see past a hyphen, a plural, or a
    pair of words in the other order.
    """
    assert measure(osl_text, declared) == "silent"


@pytest.mark.parametrize(
    "declared,osl_text",
    [
        # An abbreviation shares no letters with the phrase it stands for.
        ("AS", "The ITA file is built monthly and delivered to the mail house."),
        # `legacy extract` is in the list; this says `legacy history pull`.
        ("ARCHIVE", "A legacy history pull covering closed trades from earlier periods."),
    ],
)
def test_a_vocabulary_no_list_holds_is_an_honest_review_item(declared: str, osl_text: str) -> None:
    """What normalising cannot reach, and should not pretend to.

    No spelling rule turns ``ITA`` into ``invitation to apply``. These are raised for
    review — not at high severity — which is the honest answer: the tool has not found
    the programme's words and does not claim to know what the delivery is instead. An
    administrator adding the customer's word closes each one permanently.
    """
    assert measure(osl_text, declared) == "review"


# --- class 3: what the repair closed, and the one thing it did not -----------------


def test_the_knife_edge_case_is_gone() -> None:
    """The sharpest row in the measurement, and it no longer fires either way.

    A realistic prescreen OSL used to be silent only because its last sentence happened
    to say ``firm offer``. Rewording that one phrase — leaving a document still plainly
    a solicitation — reported it at high severity as a different programme. Both
    spellings are now silent, because ``promotional acquisition campaign`` is itself a
    thing the business says and is in the list.
    """
    osl = (
        "Purpose. A promotional acquisition campaign for non-customers. "
        "Universe. Consumers scored above the cut, excluding existing accounts and "
        "anyone on the opt-out list. An account review removes current relationships. "
        "Delivery. A monthly file to the mail house, with counts by state. "
        "Compliance. Delivered under the {phrase} provisions of the Act."
    )
    assert measure(osl.format(phrase="firm offer"), "AS") == "silent"
    assert measure(osl.format(phrase="applicable"), "AS") == "silent"


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
    ],
)
def test_generic_words_no_longer_name_a_programme(declared: str, osl_text: str) -> None:
    """The second defect, closed at the source.

    ``snapshot`` and ``historical`` used to be Archives keywords. They are ordinary
    data-delivery vocabulary that appears in a specification for every programme, and
    they let Archives clear the two-hit floor by accident — so a document whose own
    words were missed was confidently reported as Archives at high severity.

    They are gone from the shipped list, and the rule that replaced them is structural:
    a programme is named only on words **it alone claims**, so an administrator adding
    an overlapping word later cannot reintroduce this. These now raise an honest review
    item instead.
    """
    assert measure(osl_text, declared) == "review"


def test_a_programme_is_not_named_on_words_another_programme_shares() -> None:
    """The structural guard, tested directly rather than through the shipped list.

    Two programmes both claim ``monthly refresh``. However often it appears, it cannot
    say which of the two a delivery is, so it is not evidence for either.
    """
    shared = {
        "AS": ("prescreen",),
        "AM": ("monthly refresh", "account review"),
        "ARCHIVE": ("monthly refresh", "archive"),
    }
    assert (
        _measure_with(
            "A monthly refresh of the file, prepared for the usual distribution.",
            declared="AS",
            keywords=shared,
        )
        == "review"
    )


def test_two_programmes_that_look_equally_likely_name_neither() -> None:
    """A tie is not an answer.

    When the strongest other programme is only level with the next, the inputs are
    unfamiliar rather than evidence for one of them. Saying so is worth more than
    picking the first.
    """
    keywords = {
        "AS": ("prescreen",),
        "AM": ("account monitoring", "portfolio review"),
        "ARCHIVE": ("archive", "archival"),
    }
    text = "Account monitoring and a portfolio review of the archive, archival copies kept."
    assert _measure_with(text, declared="AS", keywords=keywords) == "review"


def test_the_one_case_the_deterministic_repair_does_not_close() -> None:
    """Kept deliberately, as the worked example for `docs/phase-6.18.md` 6.18f.

    This delivery is a solicitation. It says so in words no list holds — *promotional
    acquisition mailing* — and it mentions Account Monitoring's vocabulary for the
    ordinary reason that a prescreen suppresses the customers it already has. Code sees
    two AM words and none of its own, and reports at high severity.

    **No spelling rule reaches this**, because nothing is misspelled: the words really
    are AM's, and what makes them innocent is that they appear under *suppress* and
    *removes*. That is meaning, and meaning is what the model is for — asked once,
    after the code check has failed, and answering *which programme does this read
    like*, never *is this correct*, which stays code's (ADR-001).
    """
    osl = (
        "A promotional acquisition mailing. Suppress existing accounts; an account "
        "review of the current book removes anyone already on file."
    )
    assert measure(osl, "AS") == "high"


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
