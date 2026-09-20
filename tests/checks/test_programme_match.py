"""Matching a programme's keywords against a delivery's words (Phase 6.17a).

Three ways to find a keyword, and the rule that decides which keywords may name a
programme. The measured consequences are in
`tests/pipeline/test_programme_keyword_brittleness.py`; these are the mechanics.
"""

from __future__ import annotations

import pytest

from greenlight_ai.checks import programme_match as pm

# --- folding ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "word,expected",
    [
        ("accounts", "account"),
        ("archives", "archive"),
        ("solicitations", "solicitation"),
        ("policies", "policy"),
        # Short words and double-s endings are left alone: removing the `s` would be a
        # guess, and a wrong guess here is a silent false match.
        ("is", "is"),
        ("as", "as"),
        ("across", "across"),
        ("business", "business"),
        ("class", "class"),
    ],
)
def test_the_plural_fold_is_conservative(word: str, expected: str) -> None:
    assert pm.fold(word) == expected


def test_tokens_treat_every_separator_alike() -> None:
    """A hyphen, an underscore and a slash are all just word boundaries."""
    assert pm.tokens("Invitation-to-Apply") == ("invitation", "to", "apply")
    assert pm.tokens("back_file/extract") == ("back", "file", "extract")
    assert pm.tokens("  spaced   out  ") == ("spaced", "out")
    assert pm.tokens("") == ()


# --- the three ways to match ----------------------------------------------------------


def _found(keyword: str, text: str) -> bool:
    return bool(pm.hits([text], (keyword,)))


@pytest.mark.parametrize(
    "keyword,text",
    [
        # 1. Normalised substring — this is what preserves the old behaviour, and with
        #    it every inflection a substring caught for free.
        ("prescreen", "The prescreened population was scored."),
        ("archive", "Records are archived and the archives delivered."),
        ("solicitation", "Solicitations go out monthly."),
        # 2. Adjacent tokens, singular or plural.
        ("existing accounts", "Each existing account is rescored."),
        ("invitation to apply", "An invitation-to-apply mailing."),
        ("back file", "A back-file extract of prior-year records."),
        # 3. The same words close together, in any order.
        ("portfolio review", "An ongoing review of the portfolio."),
        ("account review", "A review of every account on the book."),
    ],
)
def test_a_keyword_that_is_present_is_found(keyword: str, text: str) -> None:
    assert _found(keyword, text)


@pytest.mark.parametrize(
    "keyword,text",
    [
        # Nothing of the kind is there.
        ("prescreen", "An archival snapshot of closed trades."),
        ("existing accounts", "The delivery covers new applicants only."),
        # The window does not reach across a paragraph: two words this far apart are
        # not a phrase, they are a coincidence.
        (
            "portfolio review",
            "The portfolio is delivered monthly. Counts by state, band and channel "
            "are attached, and a separate review of the mailing list is out of scope.",
        ),
        # A single word gets no window — rule 3 is for phrases only.
        ("archive", "The file is arch and ive."),
    ],
)
def test_a_keyword_that_is_absent_is_not_invented(keyword: str, text: str) -> None:
    assert not _found(keyword, text)


def test_the_window_is_bounded() -> None:
    """The window is a stated number, not an accident of the text being short."""
    near = "review " + "filler " * (pm.WINDOW - 1) + "portfolio"
    far = "review " + "filler " * (pm.WINDOW + 2) + "portfolio"
    assert _found("portfolio review", near)
    assert not _found("portfolio review", far)


def test_hits_preserves_the_order_the_programme_lists_its_words() -> None:
    """A finding quotes these back to a person, so the order should be theirs."""
    text = "A prescreen with a firm offer, run as a solicitation."
    assert pm.hits([text], ("firm offer", "prescreen", "solicitation")) == [
        "firm offer",
        "prescreen",
        "solicitation",
    ]


def test_every_part_of_the_haystack_is_searched() -> None:
    """The OSL, the configuration and the report headers are one text to this check."""
    assert pm.hits(["nothing here", "suppressions.prescreen_flag"], ("prescreen",)) == ["prescreen"]


# --- which keywords may name a programme ---------------------------------------------


def test_a_word_two_programmes_claim_is_evidence_for_neither() -> None:
    """The structural half of the 6.17a repair.

    ``snapshot`` shipped as an Archives keyword and appears in any programme's
    specification. Removing it from the seeded list fixed that instance; this rule is
    what stops an administrator recreating it.
    """
    keywords = {
        "ARCHIVE": ("archive", "snapshot"),
        "AM": ("snapshot", "account review"),
    }
    assert pm.discriminating("ARCHIVE", keywords) == ("archive",)
    assert pm.discriminating("AM", keywords) == ("account review",)


def test_sharing_is_judged_after_normalising() -> None:
    """``Firm Offer`` and ``firm-offer`` are the same word however they were typed."""
    keywords = {"AS": ("Firm Offer", "prescreen"), "AM": ("firm-offer",)}
    assert pm.discriminating("AS", keywords) == ("prescreen",)


def test_a_programme_nobody_overlaps_keeps_all_its_words() -> None:
    keywords = {"AS": ("prescreen", "firm offer"), "AM": ("account review",)}
    assert pm.discriminating("AS", keywords) == ("prescreen", "firm offer")


def test_an_unknown_programme_has_no_words() -> None:
    assert pm.discriminating("NOPE", {"AS": ("prescreen",)}) == ()
