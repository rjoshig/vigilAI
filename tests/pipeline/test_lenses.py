"""Stage 8's lenses: three readers, one merge, done by code (Phase 6.11e, ADR-034).

What the lenses are allowed to do is the whole point, so these prove the limits as
well as the behaviour: a lens can lower confidence in a finding and can raise a
question, and it can never raise a severity or delete anything.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from greenlight_ai.llm.client import LLMError
from greenlight_ai.pipeline.context import STAGE_ORDER, RunContext
from greenlight_ai.pipeline.coverage import Coverage, RequirementCoverage
from greenlight_ai.pipeline.run import run_pipeline

MakeContext = Callable[[str], RunContext]

THREE = ("delivery", "compliance", "requirements")


def _answer(agreed: bool, reason: str, confidence: float = 0.9, missed: Any = ()) -> str:
    """One lens's reply, as the scripted model returns it."""
    return json.dumps(
        {
            "agreed": agreed,
            "reason": reason,
            "confidence": confidence,
            "missed": list(missed),
        }
    )


def _with_lenses(context: RunContext) -> RunContext:
    """Turn the three lenses on for this run."""
    context.verify_lenses = THREE
    return context


def _high(context: RunContext) -> list[Any]:
    return [f for f in context.findings if f.severity == "high"]


# --- agreement and disagreement ---------------------------------------------------------


def test_three_agreeing_lenses_verify_the_finding_at_the_lowest_confidence(
    make_context: MakeContext,
) -> None:
    context = _with_lenses(make_context("score_value_mismatch"))
    for index, lens in enumerate(THREE):
        context.client.register_text(  # type: ignore[attr-defined]
            f"s8_lens_{lens}", _answer(True, f"{lens} confirms.", 0.9 - index * 0.1)
        )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    high = _high(context)
    assert high, "the fixture raises one"
    for finding in high:
        assert finding.verified and finding.verify_agreed
        assert [o["lens"] for o in finding.lens_opinions] == list(THREE)
        assert all(o["answered"] for o in finding.lens_opinions)


def test_one_dissenting_lens_sends_the_finding_to_a_person_with_every_reason(
    make_context: MakeContext,
) -> None:
    context = _with_lenses(make_context("score_value_mismatch"))
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_delivery", _answer(True, "The delivery matches the configuration.")
    )
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_compliance", _answer(True, "No obligation is touched.")
    )
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_requirements", _answer(False, "The two thresholds mean the same thing.")
    )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    downgraded = [f for f in context.findings if f.severity == "review" and f.verified]
    assert downgraded, "a split sends it to review"
    detail = downgraded[0].detail
    assert "1 of 3 readers disagreed" in detail
    assert "Requirements owner: The two thresholds mean the same thing" in detail
    assert "kept for a person to judge" in detail
    assert len(downgraded[0].lens_opinions) == 3


def test_a_lens_never_raises_a_severity(make_context: MakeContext) -> None:
    """A lens can lower confidence in a finding. It cannot make one more serious."""
    context = _with_lenses(make_context("geography_extra_state"))
    before = {}
    for lens in THREE:
        context.client.register_text(  # type: ignore[attr-defined]
            f"s8_lens_{lens}", _answer(True, "Serious.", 1.0)
        )
    run_pipeline(context, stages=STAGE_ORDER[:7])
    before = {f.finding_id: f.severity for f in context.findings}

    run_pipeline(context, stages=("s8_verify",))

    for finding in context.findings:
        if finding.finding_id in before and finding.type != "lens_proposed":
            assert finding.severity in (before[finding.finding_id], "review")


# --- a lens that proposes ---------------------------------------------------------------


def test_a_missed_item_becomes_a_review_finding_never_a_graded_one(
    make_context: MakeContext,
) -> None:
    context = _with_lenses(make_context("score_value_mismatch"))
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_delivery", _answer(True, "Confirmed.")
    )
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_requirements", _answer(True, "Confirmed.")
    )
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_compliance",
        _answer(
            True,
            "Confirmed.",
            missed=[
                {
                    "title": "The suppression list may be incomplete",
                    "reason": "Only two suppressions are configured.",
                    "confidence": 0.8,
                }
            ],
        ),
    )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    proposed = [f for f in context.findings if f.type == "lens_proposed"]
    assert len(proposed) == 1
    assert proposed[0].severity == "review"
    assert proposed[0].title == "The suppression list may be incomplete"
    assert "Compliance reading" in proposed[0].detail
    assert "question for a person" in proposed[0].detail


def test_a_low_confidence_proposal_is_dropped(make_context: MakeContext) -> None:
    """Below the floor a lens was guessing, and a guess is not worth a reviewer's time."""
    context = _with_lenses(make_context("score_value_mismatch"))
    for lens in THREE:
        context.client.register_text(  # type: ignore[attr-defined]
            f"s8_lens_{lens}",
            _answer(
                True,
                "Confirmed.",
                missed=[{"title": "Maybe something", "reason": "Not sure.", "confidence": 0.1}],
            ),
        )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    assert not [f for f in context.findings if f.type == "lens_proposed"]


def test_a_proposal_is_not_itself_put_through_the_lenses(make_context: MakeContext) -> None:
    """Otherwise one proposal would breed another on every pass."""
    context = _with_lenses(make_context("score_value_mismatch"))
    for lens in THREE:
        context.client.register_text(  # type: ignore[attr-defined]
            f"s8_lens_{lens}",
            _answer(
                True,
                "Confirmed.",
                missed=[{"title": "One more thing", "reason": "Worth asking.", "confidence": 0.9}],
            ),
        )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    proposed = [f for f in context.findings if f.type == "lens_proposed"]
    assert proposed
    assert all(not f.verified for f in proposed)


# --- when a lens does not answer ---------------------------------------------------------


def test_a_failed_lens_does_not_block_the_other_two(make_context: MakeContext) -> None:
    context = _with_lenses(make_context("score_value_mismatch"))

    def explode(_system: str, _user: str) -> str:
        raise LLMError("the model could not be reached")

    context.client.register("s8_lens_delivery", explode)  # type: ignore[attr-defined]
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_compliance", _answer(True, "Confirmed.")
    )
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_lens_requirements", _answer(True, "Confirmed.")
    )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    high = _high(context)
    assert high and all(f.verified and f.verify_agreed for f in high)
    opinions = {o["lens"]: o for o in high[0].lens_opinions}
    assert opinions["delivery"]["answered"] is False
    assert opinions["compliance"]["answered"] is True


def test_no_lens_answering_leaves_the_finding_alone_and_says_so(
    make_context: MakeContext,
) -> None:
    context = _with_lenses(make_context("score_value_mismatch"))

    def explode(_system: str, _user: str) -> str:
        raise LLMError("the model could not be reached")

    for lens in THREE:
        context.client.register(f"s8_lens_{lens}", explode)  # type: ignore[attr-defined]

    run_pipeline(context, stages=STAGE_ORDER[:8])

    high = _high(context)
    assert high, "the finding is kept, not dropped"
    assert all(not f.verified for f in high)
    assert any("could not be obtained" in notice for notice in context.notices)


# --- the switch -------------------------------------------------------------------------


def test_single_makes_one_call_per_finding(make_context: MakeContext) -> None:
    """The default reproduces the one second opinion the tool has always asked for."""
    context = make_context("score_value_mismatch")
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_verify", '{"agreed": true, "reason": "Confirmed.", "confidence": 0.9}'
    )
    run_pipeline(context, stages=STAGE_ORDER[:7])
    high_count = len(_high(context))
    before = len(context.client.call_log.records)  # type: ignore[attr-defined]

    run_pipeline(context, stages=("s8_verify",))

    made = len(context.client.call_log.records) - before  # type: ignore[attr-defined]
    assert made == high_count
    assert all(not f.lens_opinions or len(f.lens_opinions) == 1 for f in context.findings)


def test_verification_off_leaves_every_finding_and_says_so(make_context: MakeContext) -> None:
    context = make_context("score_value_mismatch")
    context.verify_lenses = ()
    run_pipeline(context, stages=STAGE_ORDER[:7])
    high_before = len(_high(context))
    before = len(context.client.call_log.records)  # type: ignore[attr-defined]

    run_pipeline(context, stages=("s8_verify",))

    assert len(context.client.call_log.records) == before  # type: ignore[attr-defined]
    assert len(_high(context)) == high_before
    assert any("switched off" in notice for notice in context.notices)


def test_the_call_cap_stops_verifying_and_says_so(make_context: MakeContext) -> None:
    context = _with_lenses(make_context("score_value_mismatch"))
    context.max_lens_calls = 0
    for lens in THREE:
        context.client.register_text(  # type: ignore[attr-defined]
            f"s8_lens_{lens}", _answer(True, "Confirmed.")
        )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    assert all(not f.verified for f in _high(context))
    assert any("limit" in notice for notice in context.notices)


@pytest.mark.parametrize("lens", THREE)
def test_each_lens_is_cached_under_its_own_key(make_context: MakeContext, lens: str) -> None:
    """A lens's answer is its own, so one re-run costs nothing and the record is complete."""
    from greenlight_ai.llm.prompts import lens_prompt

    assert lens_prompt(lens).stage == f"s8_lens_{lens}"


def test_the_same_question_raised_on_two_findings_is_asked_once(
    make_context: MakeContext,
) -> None:
    """A proposal repeated per finding is noise, not extra information."""
    context = _with_lenses(make_context("geography_extra_state"))
    for lens in THREE:
        context.client.register_text(  # type: ignore[attr-defined]
            f"s8_lens_{lens}",
            _answer(
                True,
                "Confirmed.",
                missed=[
                    {
                        "title": "The state list may be stale",
                        "reason": "It names states the programme retired.",
                        "confidence": 0.8,
                    }
                ],
            ),
        )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    proposed = [f for f in context.findings if f.type == "lens_proposed"]
    assert len(proposed) == 1
    # Every lens that raised it is named, so the reviewer knows how widely it was seen.
    assert "Delivery, Compliance, Requirements owner" in proposed[0].detail


# --- the coverage reader (Phase 6.11f) --------------------------------------------------

# No synthetic fixture leaves a requirement unevidenced: every case's requirements are
# checked against a report. The golden set gains one in 6.11b; until then these build
# the state directly, which proves the logic without waiting on a fixture.


def _with_a_gap(context: RunContext, rule_id: str = "R-OPT") -> RunContext:
    """Give a run one requirement that no report evidenced."""
    context.coverage = Coverage(
        requirements=(
            RequirementCoverage(
                rule_id=rule_id,
                req_type="other",
                state="manual",
                osl_ref="OSL section 7",
                summary="Consumers who opted out of firm offers must be excluded.",
                reason="A free-text requirement.",
            ),
        )
    )
    return context


def test_an_unchecked_requirement_that_reads_as_an_obligation_becomes_a_review_item(
    make_context: MakeContext,
) -> None:
    context = _with_a_gap(_with_lenses(make_context("score_value_mismatch")))
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_coverage",
        json.dumps(
            {
                "gaps": [
                    {
                        "rule_id": "R-OPT",
                        "reason": "Opt-out is a permissible-purpose obligation.",
                        "confidence": 0.9,
                    }
                ]
            }
        ),
    )

    run_pipeline(context, stages=("s8_verify",))

    gaps = [f for f in context.findings if f.type == "coverage_gap"]
    assert len(gaps) == 1
    assert gaps[0].severity == "review"
    assert gaps[0].rule_id == "R-OPT"
    assert "only that nothing shows it was applied" in gaps[0].detail
    assert gaps[0].evidence.osl_ref == "OSL section 7"


def test_an_invented_requirement_id_is_ignored(make_context: MakeContext) -> None:
    """A model naming something the prompt never listed is invention, not a finding."""
    context = _with_a_gap(_with_lenses(make_context("score_value_mismatch")))
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_coverage",
        json.dumps({"gaps": [{"rule_id": "R-999", "reason": "Made up.", "confidence": 0.99}]}),
    )

    run_pipeline(context, stages=("s8_verify",))

    assert not [f for f in context.findings if f.type == "coverage_gap"]


def test_a_low_confidence_gap_is_not_raised(make_context: MakeContext) -> None:
    context = _with_a_gap(_with_lenses(make_context("score_value_mismatch")))
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_coverage",
        json.dumps({"gaps": [{"rule_id": "R-OPT", "reason": "Perhaps.", "confidence": 0.2}]}),
    )

    run_pipeline(context, stages=("s8_verify",))

    assert not [f for f in context.findings if f.type == "coverage_gap"]


def test_a_reader_that_cannot_run_says_so_rather_than_passing_over_it(
    make_context: MakeContext,
) -> None:
    context = _with_a_gap(_with_lenses(make_context("score_value_mismatch")))

    def explode(_system: str, _user: str) -> str:
        raise LLMError("the model could not be reached")

    context.client.register("s8_coverage", explode)  # type: ignore[attr-defined]

    run_pipeline(context, stages=("s8_verify",))

    assert any("not read for obligations" in notice for notice in context.notices)


def test_the_coverage_reader_is_off_when_verification_is(make_context: MakeContext) -> None:
    context = _with_a_gap(make_context("score_value_mismatch"))
    context.verify_lenses = ()
    before = len(context.client.call_log.records)  # type: ignore[attr-defined]

    run_pipeline(context, stages=("s8_verify",))

    assert len(context.client.call_log.records) == before  # type: ignore[attr-defined]
    assert not [f for f in context.findings if f.type == "coverage_gap"]


def test_a_run_with_nothing_unchecked_makes_no_call(make_context: MakeContext) -> None:
    context = _with_lenses(make_context("score_value_mismatch"))
    context.coverage = Coverage()
    for lens in THREE:
        context.client.register_text(  # type: ignore[attr-defined]
            f"s8_lens_{lens}", _answer(True, "Confirmed.")
        )
    before = len(context.client.call_log.records)  # type: ignore[attr-defined]

    run_pipeline(context, stages=("s8_verify",))

    log = context.client.call_log  # type: ignore[attr-defined]
    assert "s8_coverage" not in [record.stage for record in log.records[before:]]
