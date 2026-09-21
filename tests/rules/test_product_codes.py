"""Expanding a product code into the attributes it stands for (Phase 6.22c).

Three rules under test, and each is here because of a way this goes wrong in practice:

* **Expansion is code, never the model.** Nothing in this module or its callers asks a
  model what a code contains. What the module does instead is decide whether a string
  the model read names anything at all.
* **An unknown code does not expand to nothing.** That would turn "check everything in
  ABC" into "check nothing", and the delivery would pass for the worst possible reason.
* **A shared attribute is one term with one output name.** Two codes disagreeing is a
  catalogue defect to be named, never two opinions to pick between.
"""

from __future__ import annotations

import pytest

from greenlight_ai.rules.product_codes import (
    ProductCatalogue,
    ProductCodeEntry,
    ProductMember,
)


def _code(code: str, *members: str | tuple[str, str]) -> ProductCodeEntry:
    """A code containing the named attributes; a tuple gives it an output name."""
    return ProductCodeEntry(
        code=code,
        members=tuple(
            ProductMember(m, "", index) if isinstance(m, str) else ProductMember(m[0], m[1], index)
            for index, m in enumerate(members, start=1)
        ),
    )


def _catalogue(*entries: ProductCodeEntry) -> ProductCatalogue:
    return ProductCatalogue.from_entries(entries)


class TestExpanding:
    """One code becomes its attributes; several become theirs, once each."""

    def test_a_code_expands_to_its_attributes_in_catalogue_order(self) -> None:
        catalogue = _catalogue(_code("ABC", "AT01", "ST", "SCORE_V3"))
        expansion = catalogue.expand(["ABC"])
        assert expansion.attributes == ("AT01", "ST", "SCORE_V3")
        assert expansion.by_code == {"ABC": ("AT01", "ST", "SCORE_V3")}
        assert expansion.unknown == ()

    def test_an_attribute_two_codes_share_appears_once(self) -> None:
        catalogue = _catalogue(_code("ABC", "AT01", "ST"), _code("DEF", "ST", "AGE"))
        assert catalogue.expand(["ABC", "DEF"]).attributes == ("AT01", "ST", "AGE")

    @pytest.mark.parametrize("written", ["abc", "ABC", "A-BC", "a_b_c"])
    def test_the_code_is_matched_the_way_every_other_name_is(self, written: str) -> None:
        """Separators are noise and case is noise, the ladder's second rung."""
        catalogue = _catalogue(_code("ABC", "AT01"))
        assert catalogue.knows(written)
        assert catalogue.expand([written]).attributes == ("AT01",)

    def test_an_empty_code_is_ignored_rather_than_reported_unknown(self) -> None:
        """A blank is a missing answer, not a code somebody failed to define."""
        catalogue = _catalogue(_code("ABC", "AT01"))
        expansion = catalogue.expand(["", "  ", "ABC"])
        assert expansion.attributes == ("AT01",)
        assert expansion.unknown == ()

    def test_which_code_an_attribute_came_from_can_be_named(self) -> None:
        catalogue = _catalogue(_code("ABC", "AT01"), _code("DEF", "AGE"))
        expansion = catalogue.expand(["ABC", "DEF"])
        assert expansion.code_for("AGE") == "DEF"
        assert expansion.code_for("NOT_IN_ANY") == ""


class TestAnUnknownCode:
    """The answer that matters most, because the wrong one passes a delivery."""

    def test_an_undefined_code_is_reported_and_not_silently_dropped(self) -> None:
        catalogue = _catalogue(_code("ABC", "AT01"))
        expansion = catalogue.expand(["ABC", "ZZZ"])
        assert expansion.unknown == ("ZZZ",)
        assert expansion.attributes == ("AT01",)

    def test_an_empty_catalogue_reports_every_code_as_unknown(self) -> None:
        """Not "this requirement asked for nothing"."""
        expansion = ProductCatalogue().expand(["ABC"])
        assert expansion.unknown == ("ABC",)
        assert not expansion.expanded

    def test_the_same_unknown_code_twice_is_one_report(self) -> None:
        assert ProductCatalogue().expand(["ABC", "abc"]).unknown == ("ABC",)


class TestBeyondTheCode:
    """What the delivery carries that the order never asked for."""

    def test_a_field_no_named_code_lists_is_reported(self) -> None:
        catalogue = _catalogue(_code("ABC", "AT01", "ST"))
        assert catalogue.beyond(["ABC"], ["AT01", "ST", "INTERNAL_SEQ"]) == ("INTERNAL_SEQ",)

    def test_a_respelled_field_is_not_extra(self) -> None:
        """A code listing ``opt_out`` accounts for a delivered ``OPT-OUT``."""
        catalogue = _catalogue(_code("ABC", "opt_out"))
        assert catalogue.beyond(["ABC"], ["OPT-OUT"]) == ()

    def test_a_field_delivered_under_its_output_name_is_not_extra(self) -> None:
        """The catalogue said what it would be called, so being called that is correct."""
        catalogue = _catalogue(_code("ABC", ("SCORE", "SCORE_V3")))
        assert catalogue.beyond(["ABC"], ["SCORE_V3"]) == ()

    def test_nothing_is_extra_when_no_named_code_is_known(self) -> None:
        """A catalogue that cannot say what was asked for cannot say what was extra.

        Reporting every delivered column as "beyond the code" because the code is
        undefined would bury the one finding that matters — that the code is undefined.
        """
        assert ProductCatalogue().beyond(["ABC"], ["AT01", "ST"]) == ()

    def test_the_same_extra_field_twice_is_reported_once(self) -> None:
        catalogue = _catalogue(_code("ABC", "AT01"))
        assert catalogue.beyond(["ABC"], ["EXTRA", "EXTRA"]) == ("EXTRA",)


class TestConflicts:
    """A shared attribute is one term with one output name."""

    def test_two_codes_delivering_one_attribute_differently_is_named(self) -> None:
        catalogue = _catalogue(
            _code("ABC", ("SCORE", "SCORE_V3")), _code("DEF", ("SCORE", "SCORE_V2"))
        )
        (line,) = catalogue.conflicts()
        assert "SCORE" in line and "SCORE_V3" in line and "SCORE_V2" in line

    def test_two_codes_agreeing_is_not_a_conflict(self) -> None:
        catalogue = _catalogue(
            _code("ABC", ("SCORE", "SCORE_V3")), _code("DEF", ("SCORE", "score-v3"))
        )
        assert catalogue.conflicts() == ()

    def test_an_attribute_in_one_code_only_is_not_a_conflict(self) -> None:
        assert _catalogue(_code("ABC", "AT01"), _code("DEF", "AGE")).conflicts() == ()

    def test_one_attribute_spelled_two_ways_expands_once(self) -> None:
        """The module's own headline rule, which `expand` used to break.

        `conflicts` has always asked the identity question through `squashed`, so
        ``SCORE_V3`` and ``score-v3`` are one term to it and two codes carrying them
        agree. `expand` asked it with ``!=`` on the raw string, so the same pair
        expanded to *two* attributes — and a requirement naming both codes could raise
        two findings about one attribute, while `conflicts` reported nothing to explain
        why. Two functions in one module disagreeing about what "the same attribute"
        means is the defect; this pins them together.
        """
        catalogue = _catalogue(_code("ABC", "SCORE_V3"), _code("DEF", "score-v3"))
        expansion = catalogue.expand(["ABC", "DEF"])
        assert expansion.attributes == ("SCORE_V3",)
        assert catalogue.conflicts() == ()

    def test_the_spelling_of_the_first_code_named_is_the_one_kept(self) -> None:
        """The same rule `from_entries` follows, so one order of precedence, not two."""
        catalogue = _catalogue(_code("DEF", "score-v3"), _code("ABC", "SCORE_V3"))
        assert catalogue.expand(["DEF", "ABC"]).attributes == ("score-v3",)

    def test_a_delivery_is_not_called_extra_for_either_spelling(self) -> None:
        """`beyond` already squashed; the point is that all three now agree."""
        catalogue = _catalogue(_code("ABC", "SCORE_V3"), _code("DEF", "score-v3"))
        assert catalogue.beyond(["ABC", "DEF"], ["Score-V3"]) == ()


class TestTheCatalogue:
    """Building one, and what wins when a code is defined twice."""

    def test_the_first_definition_of_a_code_wins(self) -> None:
        """Which is what lets the repository pass the most specific scope first."""
        catalogue = ProductCatalogue.from_entries([_code("ABC", "NARROW"), _code("ABC", "BROAD")])
        assert catalogue.expand(["ABC"]).attributes == ("NARROW",)

    def test_an_empty_catalogue_knows_nothing_and_raises_nothing(self) -> None:
        """The ordinary state on a deployment that defines no codes."""
        catalogue = ProductCatalogue()
        assert catalogue.codes == ()
        assert not catalogue.knows("ABC")
        assert catalogue.conflicts() == ()

    def test_a_member_with_no_output_name_is_delivered_as_itself(self) -> None:
        assert ProductMember("AT01").delivered_as == "AT01"
        assert ProductMember("SCORE", "SCORE_V3").delivered_as == "SCORE_V3"
