"""The attribute dictionary: the ladder's fourth rung, as data (Phase 6.22d).

The rules under test are the ones that make a dictionary safe to act on:

* it **never picks** — it hands the ladder alternates, and the ladder still refuses to
  answer when two candidates tie;
* a spelling recorded against one artifact is not offered for another;
* the shortlist it gives the model only ever **removes**, and never removes everything,
  because ruling out every candidate tells the model nothing.
"""

from __future__ import annotations

import pytest

from greenlight_ai.resolve import present, resolve
from greenlight_ai.resolve.dictionary import (
    AttributeDictionary,
    AttributeSpellingEntry,
    AttributeTermEntry,
)


def _term(canonical: str, *spellings: str | tuple[str, str], scope: str = "everywhere"):
    """A term; a tuple gives a spelling an artifact."""
    return AttributeTermEntry(
        canonical=canonical,
        scope=scope,
        spellings=tuple(
            AttributeSpellingEntry(s) if isinstance(s, str) else AttributeSpellingEntry(s[0], s[1])
            for s in spellings
        ),
    )


class TestLookingUpATerm:
    """Any name reaches the term; the term answers with the others."""

    def test_a_spelling_reaches_its_term(self) -> None:
        d = AttributeDictionary.from_terms([_term("AT01", "debsc_burs_atyrt_at01_1")])
        assert d.canonical("debsc_burs_atyrt_at01_1") == "AT01"

    def test_the_canonical_name_reaches_its_own_term(self) -> None:
        d = AttributeDictionary.from_terms([_term("AT01", "other")])
        assert d.term("AT01") is not None

    @pytest.mark.parametrize("written", ["opt_out", "OPT-OUT", "Opt Out", "optout"])
    def test_separators_and_case_are_noise(self, written: str) -> None:
        """The same tolerance the ladder's second rung gives every other name."""
        d = AttributeDictionary.from_terms([_term("OPT_OUT", "consumer_opt_out_flag")])
        assert d.canonical(written) == "OPT_OUT"

    def test_a_name_the_dictionary_never_saw_comes_back_unchanged(self) -> None:
        """Unchanged rather than empty: a caller must be able to go on using it."""
        assert AttributeDictionary().canonical("HOUSEHOLD_INCOME") == "HOUSEHOLD_INCOME"

    def test_the_first_term_to_claim_a_name_keeps_it(self) -> None:
        """Which is what lets the repository pass the most specific scope first."""
        d = AttributeDictionary.from_terms(
            [_term("NARROW", "SCORE", scope="config:C-1"), _term("BROAD", "SCORE")]
        )
        assert d.canonical("SCORE") == "NARROW"


class TestTheAlternates:
    """What the ladder is handed at rung 4."""

    def test_the_other_spellings_are_offered_and_the_wanted_one_is_not(self) -> None:
        """Rungs 1 to 3 have already tried the wanted name."""
        d = AttributeDictionary.from_terms([_term("AT01", "long_at01", "at_01_bureau")])
        assert d.alternates("AT01") == ("long_at01", "at_01_bureau")

    def test_asking_by_a_spelling_offers_the_canonical_name(self) -> None:
        d = AttributeDictionary.from_terms([_term("AT01", "long_at01")])
        assert d.alternates("long_at01") == ("AT01",)

    def test_a_spelling_scoped_to_one_artifact_is_not_offered_for_another(self) -> None:
        """The DIRT and the record layout need not agree with each other."""
        d = AttributeDictionary.from_terms(
            [_term("AT01", ("dirt_at01", "dirt"), ("layout_at01", "record_layout"))]
        )
        assert d.alternates("AT01", "dirt") == ("dirt_at01",)
        assert d.alternates("AT01", "record_layout") == ("layout_at01",)

    def test_a_spelling_with_no_artifact_is_offered_everywhere(self) -> None:
        """The ordinary case, and what an administrator writes by hand."""
        d = AttributeDictionary.from_terms([_term("AT01", "anywhere_at01")])
        assert d.alternates("AT01", "dirt") == ("anywhere_at01",)

    def test_an_unknown_name_offers_nothing(self) -> None:
        """Which leaves the ladder exactly where it was before the dictionary existed."""
        assert AttributeDictionary().alternates("AT01") == ()


class TestTheFourthRung:
    """The dictionary reaching through the real ladder, which is the whole point."""

    def test_a_dictionary_spelling_resolves_where_three_rungs_could_not(self) -> None:
        d = AttributeDictionary.from_terms([_term("AT01", "debsc_burs_atyrt_at01_1")])
        found = resolve("AT01", ["debsc_burs_atyrt_at01_1", "other"], d.alternates("AT01"))
        assert found is not None
        assert found.value == "debsc_burs_atyrt_at01_1"
        assert found.rung == "alternate"

    def test_present_resolves_through_the_dictionary(self) -> None:
        """The case 6.22a was honest about and could not answer."""
        d = AttributeDictionary.from_terms([_term("AT01", "debsc_burs_atyrt_at01_1")])
        match = present(
            "AT01", ["debsc_burs_atyrt_at01_1", "ST"], alternates=d.alternates("AT01", "dirt")
        )
        assert match.resolved
        assert match.found == "debsc_burs_atyrt_at01_1"

    def test_the_dictionary_never_picks_when_two_candidates_tie(self) -> None:
        """A rung that ties is a rung that failed, dictionary or not.

        The alternate ``at-01`` matches both ``at_01`` and ``AT.01`` once separators are
        noise. That is two answers, so rung 4 refuses — the dictionary offered evidence
        and the ladder still declined to guess between them.
        """
        d = AttributeDictionary.from_terms([_term("AT01", "at-01")])
        assert resolve("AT01", ["at_01", "AT.01"], d.alternates("AT01")) is None

    def test_a_dictionary_alternate_matching_one_candidate_resolves(self) -> None:
        """The same setup with the ambiguity removed, so the refusal above means something."""
        d = AttributeDictionary.from_terms([_term("AT01", "at-01")])
        found = resolve("AT01", ["at_01", "something_else"], d.alternates("AT01"))
        assert found is not None and found.value == "at_01"


class TestTheShortlist:
    """What the model is shown, after the dictionary has ruled out what it can."""

    def test_a_candidate_the_dictionary_assigns_elsewhere_is_removed(self) -> None:
        """Somebody has already answered that question; offering it is a distraction."""
        d = AttributeDictionary.from_terms([_term("AGE", "age_at_file")])
        assert d.shortlist("AT01", ["age_at_file", "mystery_column"]) == ("mystery_column",)

    def test_a_candidate_belonging_to_the_wanted_term_survives(self) -> None:
        d = AttributeDictionary.from_terms([_term("AT01", "at01_long")])
        assert d.shortlist("AT01", ["at01_long", "other"]) == ("at01_long", "other")

    def test_ruling_everything_out_gives_the_candidates_back_unchanged(self) -> None:
        """An empty shortlist tells the model nothing.

        It would turn a narrowing into a refusal the caller never asked for.
        """
        d = AttributeDictionary.from_terms([_term("AGE", "age_at_file")])
        assert d.shortlist("AT01", ["age_at_file"]) == ("age_at_file",)

    def test_an_empty_dictionary_narrows_nothing(self) -> None:
        assert AttributeDictionary().shortlist("AT01", ["a", "b"]) == ("a", "b")


class TestMerging:
    """Reading the legacy alias table alongside the dictionary (ADR-062)."""

    def test_the_dictionary_s_own_terms_win(self) -> None:
        dictionary = AttributeDictionary.from_terms([_term("NEW", "SCORE")])
        aliases = AttributeDictionary.from_terms([_term("OLD", "SCORE")])
        assert dictionary.merged(aliases).canonical("SCORE") == "NEW"

    def test_an_alias_the_dictionary_does_not_cover_still_resolves(self) -> None:
        """Nothing that matched before stops matching."""
        dictionary = AttributeDictionary.from_terms([_term("AT01", "long_at01")])
        aliases = AttributeDictionary.from_terms([_term("SCORE_V3", "revolving utilization")])
        merged = dictionary.merged(aliases)
        assert merged.canonical("revolving utilization") == "SCORE_V3"
        assert merged.canonical("long_at01") == "AT01"
