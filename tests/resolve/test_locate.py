"""The ladder's fifth rung, and what code refuses to believe (6.21a).

The call itself is small. What these tests are about is the discipline around it,
because that is what makes a model call safe to put underneath a validation result:

* it is shown **names and nothing else** (ADR-003);
* the name it quotes must be one that was offered, or it is a hallucination;
* below the floor it was guessing, and a guess tells us nothing the four deterministic
  rungs had not already;
* a run with no client gets the deterministic answer rather than an error.

And the one that matters most: what comes back is never a pass. It is a resolution
whose ``reasoned`` is ``True``, which every caller turns into a review-severity record
a person confirms.
"""

from __future__ import annotations

from typing import Any

import pytest

from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.prompts.schemas import NameLocation
from greenlight_ai.resolve.locate import CONFIDENCE_FLOOR, MAX_NAMES, locate

NAMES = ["Cover", "Accepted total", "Rejected total", "Input records"]


class _Client:
    """A stand-in that answers the locator with whatever a test needs."""

    def __init__(self, answer: Any = None, raises: bool = False) -> None:
        self.answer = answer
        self.raises = raises
        self.calls = 0
        self.user = ""
        self.system = ""

    def complete(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.system = system
        self.user = user
        if self.raises:
            raise LLMError("no answer")

        class _Result:
            def __init__(self, parsed: Any) -> None:
                self._parsed = parsed

            def parsed(self, _schema: Any) -> Any:
                return self._parsed

        return _Result(self.answer)


def _answer(**fields: Any) -> NameLocation:
    """A ``NameLocation`` with sensible defaults."""
    return NameLocation(
        **{
            "verdict": "found",
            "name": "Accepted total",
            "reason": "An accepted total is the count that passed every filter.",
            "confidence": 0.9,
            **fields,
        }
    )


def test_a_confident_answer_from_the_list_is_believed() -> None:
    client = _Client(_answer())
    found = locate(client, "Accepts", "a row label for the accepted count", NAMES)

    assert found is not None
    assert found.value == "Accepted total"
    assert found.rung == "model" and found.reasoned
    assert found.confidence == pytest.approx(0.9)
    assert "accepted total" in found.reason.lower()


def test_the_model_is_shown_names_and_nothing_else() -> None:
    """ADR-003 at the one place this rung could break it."""
    client = _Client(_answer())
    locate(client, "Accepts", "a row label for the accepted count", NAMES)

    for name in NAMES:
        assert name in client.user
    # Nothing that is not a name: no count, no cell, no row.
    assert "179224" not in client.user and "1000000" not in client.user


def test_a_name_nobody_offered_is_refused() -> None:
    """The hallucination test. Believing this would be the comparison ADR-001 forbids."""
    client = _Client(_answer(name="Settled total"))
    assert locate(client, "Accepts", "the accepted count", NAMES) is None


def test_a_reply_that_tidied_the_spacing_is_still_checked_against_the_list() -> None:
    """Refusing this would throw away a correct answer over whitespace.

    The test is still "was this one of the names offered" — it is made on the squashed
    form so a model that wrote ``accepted_total`` is checked rather than discarded, and
    what comes back is the workbook's own spelling.
    """
    client = _Client(_answer(name="accepted_total"))
    found = locate(client, "Accepts", "the accepted count", NAMES)
    assert found is not None and found.value == "Accepted total"


@pytest.mark.parametrize("verdict", ["absent", "unsure"])
def test_only_found_counts(verdict: str) -> None:
    """``absent`` is the expected answer and is not a failure on anybody's part."""
    client = _Client(_answer(verdict=verdict))
    assert locate(client, "Accepts", "the accepted count", NAMES) is None


def test_below_the_floor_is_a_guess_and_is_refused() -> None:
    client = _Client(_answer(confidence=CONFIDENCE_FLOOR - 0.01))
    assert locate(client, "Accepts", "the accepted count", NAMES) is None


def test_at_the_floor_is_believed() -> None:
    """The boundary is inclusive, so the constant means what it says."""
    client = _Client(_answer(confidence=CONFIDENCE_FLOOR))
    assert locate(client, "Accepts", "the accepted count", NAMES) is not None


def test_no_client_costs_nothing_and_raises_nothing() -> None:
    """A run with no model, or one whose budget is spent, keeps the code answer."""
    assert locate(None, "Accepts", "the accepted count", NAMES) is None


def test_a_model_that_does_not_answer_degrades() -> None:
    client = _Client(raises=True)
    assert locate(client, "Accepts", "the accepted count", NAMES) is None
    assert client.calls == 1


@pytest.mark.parametrize("wanted,names", [("", NAMES), ("Accepts", []), ("Accepts", ["", "  "])])
def test_nothing_to_ask_about_costs_no_call(wanted: str, names: list[str]) -> None:
    client = _Client(_answer())
    assert locate(client, wanted, "the accepted count", names) is None
    assert client.calls == 0


def test_the_list_shown_is_capped() -> None:
    """A workbook is not a search space."""
    client = _Client(_answer(name="sheet0"))
    many = [f"sheet{n}" for n in range(MAX_NAMES + 25)]
    locate(client, "Accepts", "the accepted count", many)

    assert f"sheet{MAX_NAMES - 1}" in client.user
    assert f"sheet{MAX_NAMES}" not in client.user


def test_duplicates_are_offered_once() -> None:
    client = _Client(_answer(name="Flow"))
    locate(client, "Flow", "the waterfall sheet", ["Flow", "Flow", "Cover"])
    assert client.user.count("- Flow") == 1
