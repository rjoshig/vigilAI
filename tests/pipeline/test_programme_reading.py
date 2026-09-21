"""Code first, the model once, code decides (Phase 6.18f, ADR-045).

The keyword check is free, exact and explainable, and Phase 6.17a made it survive a
hyphen and a plural. What it still cannot do is recognise a programme described in
words nobody taught it — that is meaning, and these tests are about the one model call
that reads for it.

The shape is the compliance locator's, deliberately: the model is asked only where the
deterministic check has already failed, it answers one narrow question, and **code does
every comparison**. The model never says whether the submitter was right.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from greenlight_ai.llm.client import LLMError
from greenlight_ai.llm.prompts.schemas import ProgrammeReading
from greenlight_ai.parsers.base import ConfigDocument, OslDocument, OslSection
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import RunGuidance
from greenlight_ai.pipeline.s7_reports import _check_programme

KEYWORDS = {
    "AS": ("prescreen", "firm offer", "invitation to apply"),
    "AM": ("account monitoring", "portfolio review", "existing accounts", "account review"),
    "ARCHIVE": ("archive", "archival"),
}
LABELS = {"AS": "Account Solicitation", "AM": "Account Monitoring", "ARCHIVE": "Archives"}

#: The delivery from the 6.17a measurement that no spelling rule reaches: a
#: solicitation in words no list holds, which mentions Account Monitoring's vocabulary
#: for the ordinary reason that a prescreen suppresses the customers it already has.
THE_HARD_CASE = (
    "A promotional acquisition mailing. Suppress existing accounts; an account "
    "review of the current book removes anyone already on file."
)


class _Client:
    """A stand-in that answers the reading prompt with whatever a test needs."""

    def __init__(self, answer: Any = None, raises: bool = False) -> None:
        self.answer = answer
        self.raises = raises
        self.calls = 0
        self.user = ""

    def complete(self, system: str, user: str, schema: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.user = user
        if self.raises:
            raise LLMError("no answer")

        class _Result:
            def __init__(self, parsed: Any) -> None:
                self._parsed = parsed

            def parsed(self, _schema: Any) -> Any:
                return self._parsed

        return _Result(self.answer)


def _build(cls: Any, **given: Any) -> Any:
    values: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in given:
            values[f.name] = given[f.name]
        elif (
            f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        ):
            continue
        elif f.type in ("str", str):
            values[f.name] = ""
        elif f.type in ("int", int):
            values[f.name] = 1
        elif "Path" in str(f.type):
            values[f.name] = Path("x")
        else:
            values[f.name] = ()
    return cls(**values)


def _context(osl_text: str, declared: str, client: Any) -> RunContext:
    context = RunContext(
        run_id="t",
        osl_path=Path("x.docx"),
        config_path=Path("x.json"),
        report_paths={},
        client=client,
        guidance=RunGuidance(
            scope_code=declared,
            scope_label=LABELS.get(declared, declared),
            programme_keywords=dict(KEYWORDS),
            programme_labels=dict(LABELS),
        ),
    )
    section = _build(OslSection, number="1", heading="Scope", level=1, paragraphs=(osl_text,))
    context.osl = _build(OslDocument, sections=(section,))
    context.config = _build(ConfigDocument, blocks=())
    return context


def _reading(**fields: Any) -> ProgrammeReading:
    return ProgrammeReading(
        **{
            "programme_code": "AS",
            "verdict": "reads_like",
            "phrases": ["promotional acquisition mailing"],
            "reason": "An outbound campaign to non-customers.",
            "confidence": 0.85,
            **fields,
        }
    )


def _run(osl_text: str, declared: str, client: Any) -> RunContext:
    context = _context(osl_text, declared, client)
    _check_programme(context)
    return context


# --- the model is asked only where code has failed ------------------------------------


def test_a_keyword_match_costs_no_model_call() -> None:
    """The common case must stay free. This is why the order is what it is."""
    client = _Client(_reading())
    context = _run("This prescreen campaign delivers a firm offer.", "AS", client)

    assert client.calls == 0
    assert context.findings == []


def test_the_model_is_asked_once_when_the_keywords_miss() -> None:
    client = _Client(_reading())
    _run(THE_HARD_CASE, "AS", client)

    assert client.calls == 1


def test_no_client_means_the_check_behaves_exactly_as_it_did() -> None:
    """The model is an addition, never a dependency. A run without one still works."""
    context = _run(THE_HARD_CASE, "AS", None)

    assert len(context.findings) == 1
    assert context.findings[0].severity == "high"
    assert context.findings[0].engine == "code"


# --- what the model is shown ----------------------------------------------------------


def test_the_prompt_offers_the_programmes_by_name_not_only_by_code() -> None:
    """A code says nothing about what a programme is, and the model has to choose."""
    client = _Client(_reading(verdict="unclear", programme_code=""))
    _run(THE_HARD_CASE, "AS", client)

    assert "Account Solicitation" in client.user
    assert "Account Monitoring" in client.user


def test_the_delivery_is_not_asked_about_when_there_is_only_one_programme() -> None:
    """Nothing to choose between, so nothing worth a call."""
    client = _Client(_reading())
    context = RunContext(
        run_id="t",
        osl_path=Path("x.docx"),
        config_path=Path("x.json"),
        report_paths={},
        client=client,
        guidance=RunGuidance(
            scope_code="AS",
            scope_label="Account Solicitation",
            programme_keywords={"AS": ("prescreen",)},
            programme_labels={"AS": "Account Solicitation"},
        ),
    )
    section = _build(OslSection, number="1", heading="S", level=1, paragraphs=("Nothing.",))
    context.osl = _build(OslDocument, sections=(section,))
    context.config = _build(ConfigDocument, blocks=())
    _check_programme(context)

    assert client.calls == 0


# --- code decides what the answer means -----------------------------------------------


def test_the_model_agreeing_closes_the_hard_case_and_names_the_words() -> None:
    """The case 6.17a measured and could not close.

    The delivery is a solicitation. Code sees two Account Monitoring words and none of
    its own, and would report at high severity. The model reads the whole thing and
    says it is what the submitter declared — so the finding drops to a question, and
    the words that would have matched are offered to an administrator.
    """
    client = _Client(_reading(programme_code="AS"))
    context = _run(THE_HARD_CASE, "AS", client)

    assert len(context.findings) == 1
    finding = context.findings[0]
    assert finding.severity == "review"
    assert finding.engine == "model"
    assert "promotional acquisition mailing" in finding.detail
    assert context.keyword_suggestions["AS"] == ("promotional acquisition mailing",)


def test_the_model_agreeing_where_code_had_nothing_is_silent() -> None:
    """A word-list gap is an administrator's problem, not a reviewer's.

    Code had only "none of its words appear" — no other programme reached the floor —
    which tells a reviewer nothing they can act on. The suggestion still goes to the
    person who can close it.
    """
    client = _Client(_reading(programme_code="AS", phrases=["promotional acquisition mailing"]))
    context = _run("A promotional acquisition mailing to non-customers.", "AS", client)

    assert context.findings == []
    assert context.keyword_suggestions["AS"] == ("promotional acquisition mailing",)


def test_the_model_disagreeing_is_the_high_finding_the_check_exists_for() -> None:
    client = _Client(_reading(programme_code="AM", phrases=["ongoing review of the book"]))
    context = _run("An ongoing review of the book, refreshed monthly.", "AS", client)

    assert len(context.findings) == 1
    finding = context.findings[0]
    assert finding.severity == "high"
    assert finding.engine == "model"
    assert "Account Monitoring" in finding.title
    assert "ongoing review of the book" in finding.detail


def test_unclear_never_raises_the_severity() -> None:
    """The model could not tell either, so a keyword coincidence is not certainty."""
    client = _Client(_reading(verdict="unclear", programme_code="", phrases=[]))
    context = _run(THE_HARD_CASE, "AS", client)

    assert len(context.findings) == 1
    assert context.findings[0].severity == "review"


# --- what code refuses to believe ------------------------------------------------------


@pytest.mark.parametrize(
    "answer,why",
    [
        (_reading(programme_code="NOPE"), "a programme nobody offered"),
        (_reading(programme_code="AS", confidence=0.2), "below the confidence floor"),
    ],
)
def test_an_answer_code_cannot_believe_leaves_the_finding_as_it_was(
    answer: ProgrammeReading, why: str
) -> None:
    """A hallucinated programme and an unconfident one both fall back to code.

    The deterministic answer is what the check would have had anyway, so refusing the
    model's is never worse than not asking — which is the property that makes asking
    safe at all.
    """
    context = _run(THE_HARD_CASE, "AS", _Client(answer))

    assert len(context.findings) == 1, why
    assert context.findings[0].severity == "high"
    assert context.findings[0].engine == "code"


def test_a_model_that_does_not_answer_changes_nothing() -> None:
    context = _run(THE_HARD_CASE, "AS", _Client(raises=True))

    assert len(context.findings) == 1
    assert context.findings[0].severity == "high"
    assert context.findings[0].engine == "code"


def test_the_model_can_soften_a_high_finding_but_never_erase_one() -> None:
    """The rule that keeps this safe, stated as its own test.

    A model agreeing with the submitter is the one answer that could hide a real
    mismatch. It buys a question, not a silence — the same line the compliance locator
    holds.
    """
    client = _Client(_reading(programme_code="AS"))
    context = _run(THE_HARD_CASE, "AS", client)

    assert len(context.findings) == 1
    assert context.findings[0].severity == "review"


# --- the suggestions ------------------------------------------------------------------


def test_suggestions_are_cleaned_and_never_duplicated() -> None:
    client = _Client(
        _reading(
            programme_code="AS",
            phrases=["  promotional   acquisition mailing ", "Promotional Acquisition Mailing"],
        )
    )
    context = _run(THE_HARD_CASE, "AS", client)

    assert context.keyword_suggestions["AS"] == ("promotional acquisition mailing",)


def test_a_suggestion_is_never_applied_by_the_run() -> None:
    """Nothing activates without a person (ADR-021).

    The run records what would have matched. The keyword list it was checked against is
    the one it started with, and stays that way until an administrator says otherwise.
    """
    client = _Client(_reading(programme_code="AS"))
    context = _run(THE_HARD_CASE, "AS", client)

    assert context.guidance.programme_keywords is not None
    assert context.guidance.programme_keywords["AS"] == KEYWORDS["AS"]
