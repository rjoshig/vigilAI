"""Proposing what a delivery calls an attribute (Phase 6.22f).

The rule with teeth is the one about ties. The record layout proposes a mapping only
when it declares **exactly one** field resembling the attribute the OSL asked for. Two
is not an answer, and offering a person a choice between them — without showing them the
workbook — would be asking them to make the comparison ADR-001 keeps out of a guess's
hands, wearing an approval button.
"""

from __future__ import annotations

from greenlight_ai.checks.attribute_suggestions import (
    AttributeSuggestion,
    from_record_layout,
    merge,
)


class TestFromTheRecordLayout:
    """Read in code out of a document the delivery carried. No model call at all."""

    def test_one_resembling_field_is_proposed(self) -> None:
        (proposal,) = from_record_layout(["AT01"], ["debsc_burs_atyrt_at01_1", "ST"])
        assert proposal.wanted == "AT01"
        assert proposal.found == "debsc_burs_atyrt_at01_1"
        assert proposal.origin == "record_layout"
        assert "no model was asked" in proposal.reason

    def test_two_resembling_fields_propose_nothing(self) -> None:
        """A tie is not an answer, at any rung and in any artifact."""
        assert from_record_layout(["AT01"], ["at01_a_long_one", "at01_b_long_one"]) == []

    def test_nothing_resembling_proposes_nothing(self) -> None:
        assert from_record_layout(["AT01"], ["STATE", "AGE"]) == []

    def test_no_layout_proposes_nothing(self) -> None:
        """The ordinary delivery, which carried none."""
        assert from_record_layout(["AT01"], []) == []

    def test_each_unresolved_attribute_gets_its_own_proposal(self) -> None:
        proposals = from_record_layout(
            ["AT01", "ST"], ["debsc_burs_atyrt_at01_1", "debsc_burs_atyrt_st_1"]
        )
        assert [(p.wanted, p.found) for p in proposals] == [
            ("AT01", "debsc_burs_atyrt_at01_1"),
            ("ST", "debsc_burs_atyrt_st_1"),
        ]

    def test_the_confidence_is_about_provenance_not_certainty(self) -> None:
        """1.0 says "a document said so", not "this is definitely right".

        A person still decides, which is the whole of ADR-021.
        """
        (proposal,) = from_record_layout(["AT01"], ["debsc_burs_atyrt_at01_1"])
        assert proposal.confidence == 1.0


class TestMerging:
    """What is worth showing, once."""

    def _model(self, wanted: str, found: str, confidence: float = 0.8) -> AttributeSuggestion:
        return AttributeSuggestion(
            artifact="dirt",
            wanted=wanted,
            found=found,
            origin="model",
            confidence=confidence,
        )

    def _layout(self, wanted: str, found: str) -> AttributeSuggestion:
        return AttributeSuggestion(
            artifact="dirt", wanted=wanted, found=found, origin="record_layout", confidence=1.0
        )

    def test_the_same_mapping_twice_is_one_offer(self) -> None:
        out = merge([self._layout("AT01", "long_at01"), self._model("AT01", "long_at01")])
        assert len(out) == 1
        assert out[0].origin == "record_layout"

    def test_the_same_mapping_spelled_differently_is_one_offer(self) -> None:
        """One run saying ``AT01`` and another ``at-01`` is not two things to click."""
        out = merge([self._model("AT01", "long_at01"), self._model("at-01", "long-at01")])
        assert len(out) == 1

    def test_a_mapping_the_dictionary_already_holds_is_not_offered(self) -> None:
        """Listing it again is how a console teaches people to click past it."""
        out = merge([self._model("AT01", "long_at01")], known={"AT01": ["AT01", "long_at01"]})
        assert out == []

    def test_a_mapping_for_a_known_attribute_under_a_new_spelling_is_still_offered(self) -> None:
        out = merge([self._model("AT01", "brand_new")], known={"AT01": ["AT01", "long_at01"]})
        assert len(out) == 1

    def test_a_blank_side_is_dropped_rather_than_offered(self) -> None:
        assert merge([self._model("AT01", "  "), self._model("", "x")]) == []

    def test_proposal_order_is_kept(self) -> None:
        """Which is what puts the record layout's free reading above the model's."""
        out = merge([self._layout("ST", "long_st"), self._model("AT01", "long_at01")])
        assert [p.wanted for p in out] == ["ST", "AT01"]
