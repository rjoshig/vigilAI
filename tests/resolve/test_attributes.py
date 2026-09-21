"""Telling *missing* apart from *could not resolve* (Phase 6.22a).

One property matters more than any individual case here: **an attribute the delivery
does not carry is still a violation.** The repair widens what counts as "we cannot
tell"; it must not widen it so far that a genuinely undelivered attribute is softened
into a review record, because that would trade a false positive for a false negative,
and a false negative is the one this product cannot afford.

The two fixture cases are the poles. ``attribute_renamed`` is a correct delivery whose
DIRT spells everything the long way — nothing there is missing. ``attributes_missing_
in_report`` is a delivery that really is short one attribute — that one must still be
high severity.
"""

from __future__ import annotations

import pytest

from greenlight_ai.resolve.attributes import MAX_NEAR, near_names, present

#: The DIRT of the ``attribute_renamed`` fixture: every attribute delivered, under the
#: long name the source system gives it.
DELIVERED = [
    "debsc_burs_atyrt_score_v3_1",
    "debsc_burs_atyrt_age_1",
    "debsc_burs_atyrt_st_1",
    "debsc_burs_atyrt_rev_util_1",
    "debsc_burs_atyrt_open_trades_1",
]

#: What the OSL asks for, spelled its own way.
ASKED = ["SCORE_V3", "AGE", "ST", "REV_UTIL", "OPEN_TRADES"]


@pytest.mark.parametrize("wanted", ASKED)
def test_a_renamed_attribute_is_unresolved_not_missing(wanted: str) -> None:
    """The case the phase exists for.

    Before this module, every one of these produced a high-severity "the reports are
    missing this attribute" about a delivery that carried it.
    """
    match = present(wanted, DELIVERED)
    assert not match.resolved
    assert match.plausible, f"{wanted} should be recognised as probably present"


def test_a_short_name_still_resembles_its_long_form() -> None:
    """``ST`` is the case a substring test alone cannot reach.

    Two letters are too few for a substring to be evidence, so the whole-word test is
    what carries this one. Without it ``ST`` reads as missing and a correct delivery
    keeps its high-severity finding.
    """
    assert near_names("ST", DELIVERED) == ("debsc_burs_atyrt_st_1",)


def test_an_attribute_that_was_not_delivered_is_still_missing() -> None:
    """The regression that matters most.

    ``INCOME_EST`` is genuinely absent from the ``attributes_missing_in_report``
    fixture. A loose near-miss test would find ``ST`` inside ``incomeest`` and soften
    a real defect into a review record.
    """
    match = present("INCOME_EST", ["SCORE_V3", "AGE", "ST", "REV_UTIL"])
    assert not match.resolved
    assert not match.plausible
    assert match.near == ()


def test_two_letters_buried_in_a_longer_name_are_not_evidence() -> None:
    """The specific coincidence the length floor exists to reject."""
    assert near_names("INCOME_EST", ["ST"]) == ()


def test_an_exact_name_resolves_on_the_first_rung() -> None:
    """Nothing that matched before this module stops matching (ADR-054)."""
    match = present("AGE", ["SCORE_V3", "AGE", "ST"])
    assert match.resolved
    assert match.found == "AGE"
    assert match.rung == "exact"


def test_separators_are_noise() -> None:
    """The ladder's second rung, reached through this helper."""
    match = present("SCORE_V3", ["score v3", "AGE"])
    assert match.found == "score v3"
    assert match.rung == "squashed"


def test_a_seeded_alias_still_wins() -> None:
    """The legacy alias table must keep working, and keep winning.

    A deployment that hand-entered an alias has to behave exactly as it did, or this
    repair would quietly change what matches.
    """

    def canonical(name: str) -> str:
        return {"score": "score", "SCORE_V3": "score"}.get(name, name.lower())

    match = present("score", ["SCORE_V3"], canonical=canonical)
    assert match.resolved
    assert match.found == "SCORE_V3"
    assert match.rung == "exact"


def test_an_administrators_spelling_resolves_on_the_fourth_rung() -> None:
    """What the dictionary will supply in 6.22d, passed by hand here."""
    match = present("AT01", ["debsc_burs_atyrt_at01_1"], alternates=["debsc_burs_atyrt_at01_1"])
    assert match.resolved
    assert match.rung == "alternate"


def test_a_long_name_is_found_inside_a_longer_one() -> None:
    """The substring test, above the floor. ``at01`` is four characters."""
    assert near_names("AT01", ["debsc_burs_atyrt_at01_1"]) == ("debsc_burs_atyrt_at01_1",)


def test_near_misses_are_capped() -> None:
    """A finding quotes enough to recognise the answer, not a column dump."""
    many = [f"prefix_score_v3_{index}" for index in range(MAX_NEAR + 5)]
    assert len(near_names("SCORE_V3", many)) == MAX_NEAR


def test_the_same_name_twice_is_one_near_miss() -> None:
    """A workbook repeating a column is not an ambiguity anybody can act on."""
    assert near_names("AT01", ["at01_x", "at01_x"]) == ("at01_x",)


def test_an_empty_name_resolves_to_nothing() -> None:
    """A rule that names no attribute asks no question."""
    match = present("   ", ["AGE"])
    assert not match.resolved
    assert not match.plausible
