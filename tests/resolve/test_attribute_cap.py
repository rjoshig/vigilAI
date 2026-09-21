"""The run's cap on attribute lookups, and the shortlist below it (Phase 6.22d).

The cap is **soft**, and everything here is about what that word means. Past it the
resolver stops asking and the run records what it did not look for; nothing is refused,
no delivery fails over a budget, and the checks that needed those names have already
said separately that they could not be evaluated. The precedent is
``s6_reverse._may_locate``, which degrades the same way for the same reason.
"""

from __future__ import annotations

from typing import Any

from greenlight_ai.llm.client import LLMClient
from greenlight_ai.llm.prompts.schemas import NameLocation
from greenlight_ai.resolve.dictionary import (
    AttributeDictionary,
    AttributeSpellingEntry,
    AttributeTermEntry,
)
from greenlight_ai.resolve.layout import LayoutResolver


class _Answering:
    """A stand-in adapter that always names the first candidate it is shown."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen: list[list[str]] = []

    def complete(self, system: str, user: str, schema: Any = None, **_: Any) -> Any:
        """Answer the locator, recording the candidate list it was shown.

        The prompt's worked examples are themselves bulleted lists, so the candidates
        are the block after the **last** "Names available:" — not every ``- `` line in
        the rendered prompt.
        """
        self.calls += 1
        tail = user.rsplit("Names available:", 1)[-1]
        names = [line[2:] for line in tail.splitlines() if line.startswith("- ")]
        self.seen.append(names)
        answer = NameLocation(
            verdict="found",
            name=names[0] if names else "",
            confidence=0.9,
            reason="a stand-in answered",
        )

        class _Result:
            def parsed(self, _schema: Any) -> Any:
                return answer

        return _Result()


def _resolver(cap: int, dictionary: AttributeDictionary | None = None) -> LayoutResolver:
    """A resolver with a stand-in adapter and the given cap."""
    client: LLMClient = _Answering()  # type: ignore[assignment]
    return LayoutResolver(
        client=client,
        dictionary=dictionary or AttributeDictionary(),
        max_attribute_calls=cap,
    )


class TestTheCap:
    """How many times a run may ask, and what happens after that."""

    def test_within_the_cap_the_model_is_asked(self) -> None:
        resolver = _resolver(2)
        assert resolver.name("AT01", ["mystery_a"], kind="attribute") is not None
        assert resolver.attribute_calls == 1
        assert resolver.capped == []

    def test_past_the_cap_it_stops_asking_and_records_what_it_skipped(self) -> None:
        resolver = _resolver(1)
        resolver.name("AT01", ["mystery_a"], kind="attribute")
        assert resolver.name("AT02", ["mystery_b"], kind="attribute") is None
        assert resolver.attribute_calls == 1
        assert resolver.capped == ["AT02"]

    def test_a_cap_of_zero_never_asks(self) -> None:
        resolver = _resolver(0)
        assert resolver.name("AT01", ["mystery_a"], kind="attribute") is None
        assert resolver.attribute_calls == 0
        assert resolver.capped == ["AT01"]

    def test_the_cap_does_not_touch_sheets_columns_or_labels(self) -> None:
        """It is a cap on *attribute* lookups. 6.21a's budget is separate and unchanged."""
        resolver = _resolver(0)
        assert resolver.name("Attributes", ["Attribute Summary"], kind="sheet") is not None
        assert resolver.attribute_calls == 0

    def test_the_same_name_twice_costs_one_call(self) -> None:
        """The resolver's own cache, which predates the cap and still applies."""
        resolver = _resolver(5)
        resolver.name("AT01", ["mystery_a"], kind="attribute")
        resolver.name("AT01", ["mystery_a"], kind="attribute")
        assert resolver.attribute_calls == 1

    def test_the_same_capped_name_twice_is_recorded_once(self) -> None:
        resolver = _resolver(0)
        resolver.name("AT01", ["mystery_a"], kind="attribute")
        resolver.name("AT01", ["mystery_b"], kind="attribute")
        assert resolver.capped == ["AT01"]


class TestWhatTheModelIsShown:
    """The deterministic shortlist, applied before the call rather than after it."""

    def test_the_dictionary_removes_a_candidate_it_assigns_elsewhere(self) -> None:
        """Somebody has already answered that ``age_at_file`` is ``AGE``."""
        dictionary = AttributeDictionary.from_terms(
            [
                AttributeTermEntry(
                    canonical="AGE", spellings=(AttributeSpellingEntry("age_at_file"),)
                )
            ]
        )
        resolver = _resolver(2, dictionary)
        resolver.name("AT01", ["age_at_file", "mystery_column"], kind="attribute")

        client: Any = resolver.client
        assert client.seen == [["mystery_column"]]

    def test_a_name_the_dictionary_resolves_costs_no_call_at_all(self) -> None:
        """Rung 4 answered, so rung 5 is never reached — which is the point of the rung."""
        dictionary = AttributeDictionary.from_terms(
            [
                AttributeTermEntry(
                    canonical="AT01",
                    spellings=(AttributeSpellingEntry("debsc_burs_atyrt_at01_1"),),
                )
            ]
        )
        resolver = _resolver(5, dictionary)
        found = resolver.name("AT01", ["debsc_burs_atyrt_at01_1", "other"], kind="attribute")

        assert found is not None
        assert found.rung == "alternate"
        assert resolver.attribute_calls == 0


class TestWhatIsRecorded:
    """A name the model reached is offered to a person, like any other (6.21b)."""

    def test_an_attribute_the_model_read_is_kept_as_a_reasoned_name(self) -> None:
        resolver = _resolver(2)
        resolver.name("AT01", ["mystery_a"], kind="attribute", artifact="dirt")

        (reasoned,) = resolver.reasoned
        assert reasoned.kind == "attribute"
        assert reasoned.wanted == "AT01"
        assert reasoned.found == "mystery_a"
        assert reasoned.artifact == "dirt"
