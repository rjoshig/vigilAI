"""The comparison that asks whether the artifacts belong to the delivery (ADR-041).

Every function under test is pure, so these are ordinary value tests: no session, no
fixtures on disk, no model. The cases are the ones the review found in the wild — a
mistyped configuration id, a customer written with and without its suffix, and a
configuration that names no customer at all.
"""

from __future__ import annotations

import datetime as dt

import pytest

from greenlight_ai.checks import artifact_match as am


class TestNormalisers:
    """Both normalisers, which decide what counts as 'nearly the same'."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("CFG-GEO-02", "CFGGEO02"),
            ("cfg_geo_02", "CFGGEO02"),
            ("CFG GEO 02", "CFGGEO02"),
            ("  cfg-geo-02  ", "CFGGEO02"),
        ],
    )
    def test_identifier_ignores_case_and_separators(self, value: str, expected: str) -> None:
        """An id written four ways compares as one."""
        assert am.normalize_identifier(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("Acme Card Services", "acme card services"),
            ("ACME Card Services, Inc.", "acme card services"),
            ("Acme Card Services LLC", "acme card services"),
            ("  acme   card  services ", "acme card services"),
        ],
    )
    def test_company_drops_suffixes_and_punctuation(self, value: str, expected: str) -> None:
        """A company suffix is noise for the purpose of recognising the customer."""
        assert am.normalize_company(value) == expected

    def test_a_name_of_nothing_but_suffixes_keeps_its_words(self) -> None:
        """Stripping everything would compare one empty string with another."""
        assert am.normalize_company("Holdings Group") == "holdings group"


class TestConfigurationId:
    """The field whose mismatch silently disabled drift."""

    def test_identical_ids_match(self) -> None:
        """The ordinary case needs nobody's attention."""
        result = am.compare_configuration_id("CFG-GEO-02", "CFG-GEO-02")
        assert result.kind == "match"
        assert result.agrees

    def test_the_review_case_is_different(self) -> None:
        """The run that passed: a typed id against an unrelated declared one."""
        result = am.compare_configuration_id("CFG-DOES-NOT-EXIST-999", "CFG-SYNTH-GEO-02")
        assert result.kind == "different"
        assert not result.agrees
        assert result.submitted == "CFG-DOES-NOT-EXIST-999"
        assert result.declared == "CFG-SYNTH-GEO-02"
        assert result.source == "the configuration's 'configuration_id'"

    def test_a_differently_punctuated_id_is_near_not_different(self) -> None:
        """Shown, because it is probably the same id — but never passed silently."""
        result = am.compare_configuration_id("cfg_geo_02", "CFG-GEO-02")
        assert result.kind == "near"
        assert not result.agrees

    def test_an_unreadable_configuration_declares_nothing(self) -> None:
        """Absence is not disagreement; the parser reports a broken file."""
        assert am.compare_configuration_id("CFG-GEO-02", "").kind == "absent"


class TestCustomer:
    """The field the configuration carries and nothing ever read."""

    def test_the_review_case_is_different(self) -> None:
        """The run that passed: a customer nobody's configuration named."""
        result = am.compare_customer("Totally Different Bank PLC", "Acme Card Services")
        assert result.kind == "different"
        assert not result.agrees

    def test_a_suffix_difference_is_near(self) -> None:
        """Renaming to Inc. does not make it a different customer, but it is shown."""
        result = am.compare_customer("Acme Card Services", "ACME Card Services, Inc.")
        assert result.kind == "near"
        assert not result.agrees

    def test_a_configuration_naming_no_customer_is_absent(self) -> None:
        """A configuration without a customer has contradicted nobody."""
        result = am.compare_customer("Acme Card Services", "")
        assert result.kind == "absent"
        assert result.agrees


class TestCreditDate:
    """Compared as a date wherever the spelling parses."""

    def test_the_same_date_spelled_differently_matches(self) -> None:
        """A report writing 03/31/2026 agrees with a submitter writing 2026-03-31."""
        result = am.compare_credit_date(dt.date(2026, 3, 31), "03/31/2026", "counts · As-of")
        assert result.kind == "match"

    @pytest.mark.parametrize("spelling", ["2026-03-31", "31 March 2026", "31-Mar-2026", "20260331"])
    def test_every_spelling_the_reports_use_is_read(self, spelling: str) -> None:
        """The reader mirrors the writer in stage 7; they stay together deliberately."""
        assert am.compare_credit_date(dt.date(2026, 3, 31), spelling).kind == "match"

    def test_a_different_date_is_reported_as_a_mismatch(self) -> None:
        """The thing the old presence test could never say."""
        result = am.compare_credit_date(dt.date(2026, 4, 30), "2026-03-31", "counts · As-of")
        assert result.kind == "different"
        assert result.submitted == "2026-04-30"
        assert result.declared == "2026-03-31"

    def test_no_submitted_date_compares_to_nothing(self) -> None:
        """A date nobody stated cannot disagree with anything."""
        assert am.compare_credit_date(None, "2026-03-31").kind == "absent"

    def test_no_labelled_date_compares_to_nothing(self) -> None:
        """Absence of evidence is reported as absence, not as a mismatch."""
        assert am.compare_credit_date(dt.date(2026, 3, 31), "").kind == "absent"


class TestDisagreements:
    """What the caller acts on."""

    def test_only_the_unhappy_results_survive(self) -> None:
        """Matches and absences are filtered out; the rest are shown in order."""
        results = am.compare_run(
            submitted_configuration_id="CFG-A",
            submitted_customer="Acme",
            submitted_credit_date=None,
            declared_configuration_id="CFG-B",
            declared_customer="",
        )
        unhappy = am.disagreements(results)
        assert [r.field for r in unhappy] == ["configuration_id"]

    def test_a_clean_submission_has_nothing_to_accept(self) -> None:
        """The ordinary run: everything agrees and nobody is asked anything."""
        results = am.compare_run(
            submitted_configuration_id="CFG-A",
            submitted_customer="Acme Card Services",
            submitted_credit_date=dt.date(2026, 3, 31),
            declared_configuration_id="CFG-A",
            declared_customer="Acme Card Services",
            declared_credit_date="2026-03-31",
        )
        assert am.disagreements(results) == ()
