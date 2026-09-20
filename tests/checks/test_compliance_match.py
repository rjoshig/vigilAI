"""Finding where a compliance rule is implemented (Phase 6.15, option C).

These are the measured failure shapes from `docs/phase-6.15.md`, turned into tests. The
one that mattered most is the last class: a substring test could not tell a control that
is *absent* from one that is *spelled differently*, and reported both at high severity.

The final class is as important as the rest — widening the match must not stop the check
reporting a control that genuinely is not there.
"""

from __future__ import annotations

import pytest

from greenlight_ai.checks import compliance_match as cm

#: A configuration implementing the three controls exactly as the rules name them.
PLAIN: list[tuple[str, object]] = [
    ("suppressions.ofac", True),
    ("suppressions.deceased", True),
    ("suppressions.optout", True),
    ("output.format", "csv"),
]


class TestNormalising:
    """Case, underscores and hyphens are noise in a key name."""

    @pytest.mark.parametrize("value", ["opt_out", "optOut", "OPT-OUT", "opt out", "optout"])
    def test_one_key_written_five_ways(self, value: str) -> None:
        """A customer's house style should not be a compliance finding."""
        assert cm.normalize_segment(value) == "optout"

    def test_an_array_index_is_not_part_of_the_key(self) -> None:
        """``rules[2]`` is the same key as ``rules``."""
        assert cm.normalize_segment("rules[2]") == "rules"


class TestTheMeasuredFailures:
    """Each row of the table in `docs/phase-6.15.md`."""

    def test_exactly_as_named(self) -> None:
        """The ordinary case, which worked before and must still work."""
        assert cm.matches("suppressions.ofac", PLAIN)

    def test_a_different_spelling(self) -> None:
        """One false HIGH before: the rule says optout, the config says opt_out."""
        blocks = [("suppressions.opt_out", True)]
        assert cm.matches("suppressions.optout", blocks)

    def test_nested_one_level_deeper(self) -> None:
        """Three false HIGH before, and the sharpest row in the table.

        The parser groups a nested object into one block, so the control is a key
        inside ``suppressions.lists`` rather than part of any path.
        """
        blocks = [("suppressions.lists", {"ofac": True, "deceased": True, "optout": True})]
        assert cm.matches("suppressions.ofac", blocks)
        assert cm.matches("suppressions.deceased", blocks)

    def test_grouped_under_another_key_needs_an_alternate(self) -> None:
        """Three false HIGH before. No amount of normalising reaches it — a person does."""
        blocks = [("exclusions.ofac", True)]
        assert not cm.matches("suppressions.ofac", blocks)
        assert cm.matches("suppressions.ofac", blocks, ["exclusions.ofac"])

    def test_a_vendor_name_needs_an_alternate(self) -> None:
        """Three false HIGH before. `sdn_screening` is OFAC, and only a person knows."""
        blocks = [("suppressions.sdn_screening", True)]
        assert cm.matches("suppressions.ofac", blocks, ["suppressions.sdn_screening"])


class TestNothingThatMatchedBeforeStopsMatching:
    """The widening is additive, which is what makes it safe to ship."""

    def test_the_accidental_substring_match_is_kept(self) -> None:
        """``suppressions.ofac`` found ``suppressions.ofac_sdn`` by luck of substring.

        It happened to be the right answer, so segment matching alone would have been a
        regression. Both tests run, and either one counts.
        """
        assert cm.matches("suppressions.ofac", [("suppressions.ofac_sdn", True)])

    def test_the_matched_path_says_how_it_was_found(self) -> None:
        """A finding should be able to say it matched via an alternate."""
        hits = cm.matches(
            "suppressions.ofac",
            [("suppressions.sdn_screening", True)],
            ["suppressions.sdn_screening"],
        )
        assert hits[0].via == "suppressions.sdn_screening"


class TestAbsenceIsStillReported:
    """The half that must not break: a control that is not there is still not there."""

    def test_a_missing_control_matches_nothing(self) -> None:
        """The reason the check exists at all."""
        assert cm.matches("suppressions.optout", [("suppressions.ofac", True)]) == ()

    def test_an_unrelated_config_matches_nothing(self) -> None:
        """Widening must not turn the matcher into something that matches anything."""
        blocks = [("output.format", "csv"), ("dedupe.key", ["SSN"]), ("input.source", "warehouse")]
        assert cm.matches("suppressions.ofac", blocks) == ()

    def test_a_rule_with_no_path_matches_nothing(self) -> None:
        """An unconfigured rule must not silently match every block."""
        assert cm.matches("", PLAIN) == ()
        assert cm.matches("   ", PLAIN) == ()

    def test_the_substring_test_stays_loose_and_that_is_the_deal(self) -> None:
        """A known looseness, kept deliberately and worth stating.

        The substring test cannot tell ``suppressions.ofac_sdn`` — a real OFAC control
        under a vendor name — from ``suppressions.ofacish_thing``, which is not one.
        Both contain the rule's characters once separators are removed.

        Dropping the substring test would fix this and would also stop finding
        ``ofac_sdn``, which the old behaviour found by luck and which is the right
        answer. Between a rule that occasionally matches too generously and one that
        reports a real control as missing at high severity, the generous one is the
        safer failure: it is visible on the finding, which names the path it matched.

        Narrowing this properly is what the model is for, and that is 6.15 option A.
        """
        hits = cm.matches("suppressions.ofac", [("suppressions.ofacish_thing", True)])
        assert hits, "the substring test is expected to match here"
        assert hits[0].exact is False, "and to report that it is not where the rule says"
