"""The deterministic rungs, and the two rules that make them defensible (6.21a).

Two properties matter more than any individual case here:

* **Nothing that matched before stops matching.** Rung 1 *is* the case-insensitive
  equality every caller used before this package existed, so every name that resolved
  then resolves now, on the same rung.
* **A tie is not an answer.** Two candidates matching equally well is the case a person
  or the model should settle, and a ladder that picked one would be making a comparison
  nobody could reproduce.
"""

from __future__ import annotations

import pytest

from greenlight_ai.resolve import resolve
from greenlight_ai.resolve.ladder import MAX_EXTRA_TOKENS

#: The sheets a real delivery renamed, from the ``layout_drift`` fixture. Every one of
#: them matched nothing before Phase 6.21.
DRIFTED = [
    ("Attributes", "Attribute Summary"),
    ("Attribute", "Attribute Name"),
    ("States", "State Breakdown"),
    ("State", "State Code"),
    ("Fields", "Field Values"),
    ("Flow", "Record Flow"),
]


@pytest.mark.parametrize("wanted,spelled", DRIFTED)
def test_the_old_rule_would_have_missed_every_drifted_name(wanted: str, spelled: str) -> None:
    """The before half of the phase's first acceptance criterion.

    This is the test that makes the rest of the file mean something: each of these
    pairs is a name a real report could carry and the pre-6.21 lookup — lowercase,
    strip, compare — would have returned nothing for.
    """
    assert wanted.strip().lower() != spelled.strip().lower()


@pytest.mark.parametrize("wanted,spelled", DRIFTED)
def test_the_ladder_finds_every_drifted_name(wanted: str, spelled: str) -> None:
    """And the after half: the same pairs resolve, on the token rung."""
    found = resolve(wanted, ["Cover", spelled, "Notes"])
    assert found is not None
    assert found.value == spelled
    assert found.rung == "tokens"
    assert found.confidence == 1.0


def test_an_exact_name_resolves_on_the_first_rung() -> None:
    """The behaviour every caller had before, unchanged and still first."""
    found = resolve("Attributes", ["Summary", "Attributes", "Sample"])
    assert found is not None and found.value == "Attributes"
    assert found.rung == "exact" and found.exact


def test_case_and_surrounding_space_are_not_a_difference() -> None:
    """``  attributes `` is ``Attributes``, which is what the old rule said too."""
    found = resolve("  attributes ", ["Summary", "Attributes"])
    assert found is not None and found.value == "Attributes" and found.rung == "exact"


@pytest.mark.parametrize("spelled", ["Delivered_count", "Delivered  count", "DELIVERED-COUNT"])
def test_separators_are_noise(spelled: str) -> None:
    """The 6.16d measurement, now answered one rung up rather than per caller."""
    found = resolve("Delivered count", ["Input", spelled])
    assert found is not None and found.value == spelled and found.rung == "squashed"


def test_spelling_settles_a_case_insensitive_tie() -> None:
    """A counts report carries a step called ``input`` and a total called ``Input``.

    They are different rows. Whichever is written the way the caller wrote it is the
    one meant — which is strictly better than the pre-6.21 rule, where document order
    decided and the answer depended on where openpyxl happened to put the row.
    """
    found = resolve("Input", ["input", "geography", "Input"])
    assert found is not None and found.value == "Input"

    found = resolve("input", ["input", "geography", "Input"])
    assert found is not None and found.value == "input"


def test_a_case_insensitive_tie_nothing_spells_exactly_takes_the_first() -> None:
    """Which is the pre-6.21 behaviour, preserved deliberately rather than by accident."""
    found = resolve("INPUT", ["input", "Input"])
    assert found is not None and found.value == "input"


def test_two_candidates_on_a_widened_rung_is_not_an_answer() -> None:
    """The rule that keeps a widened rung from guessing.

    ``Attribute Summary`` and ``Attribute Detail`` both carry the word asked for. One
    of them is the statistics sheet and the ladder cannot say which, so it says
    nothing and the question goes to the model with both still on the table.
    """
    assert resolve("Attributes", ["Attribute Summary", "Attribute Detail"]) is None


def test_the_same_name_listed_twice_is_not_a_tie() -> None:
    """A workbook repeating a name has not created an ambiguity anybody can act on."""
    found = resolve("Flow", ["Flow", "Flow"])
    assert found is not None and found.value == "Flow"


def test_a_candidate_with_fewer_words_never_matches_on_the_token_rung() -> None:
    """Dropping a word is how a narrower sheet gets mistaken for a wider one.

    ``Accepts by state`` must not resolve to ``Accepts``: the second is a total and the
    first is a breakdown, and answering a request for the breakdown with the total
    would be wrong in a way nobody would notice.
    """
    assert resolve("Accepts by state", ["Accepts"]) is None


def test_more_than_a_couple_of_extra_words_is_a_different_name() -> None:
    """Past the cap it is a different sheet, not the same one spelled longer."""
    too_far = "Attribute " + " ".join(f"word{n}" for n in range(MAX_EXTRA_TOKENS + 1))
    assert resolve("Attribute", [too_far]) is None


def test_plurals_fold_but_short_words_do_not() -> None:
    """``accounts`` is ``account``; ``gross`` is not ``gros``."""
    found = resolve("Accounts", ["Account Summary"])
    assert found is not None and found.rung == "tokens"
    assert resolve("Gross", ["Gros Summary"]) is None


def test_an_alternate_reaches_what_no_amount_of_normalising_does() -> None:
    """The fourth rung: a different word, which only a person can supply."""
    found = resolve("Accepts", ["Records shipped", "Input"], ["Records shipped"])
    assert found is not None
    assert found.value == "Records shipped" and found.rung == "alternate"


def test_an_alternate_never_overrules_a_rung_above_it() -> None:
    """An administrator's synonym does not get to beat the name actually asked for."""
    found = resolve("Accepts", ["Accepts", "Records shipped"], ["Records shipped"])
    assert found is not None and found.value == "Accepts" and found.rung == "exact"


@pytest.mark.parametrize(
    "wanted,candidates",
    [("", ["Flow"]), ("Flow", []), ("   ", ["Flow"]), ("Flow", ["Cover", "Notes"])],
)
def test_nothing_to_resolve_resolves_to_nothing(wanted: str, candidates: list[str]) -> None:
    """``None`` is "code cannot say", never "absent" — the caller decides what to do."""
    assert resolve(wanted, candidates) is None
