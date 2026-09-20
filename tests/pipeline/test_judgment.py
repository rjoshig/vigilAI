"""Judgment checks, finished under ADR-001 (Phase 6.13c).

A judgment check was definable in the console, stored, scoped, loaded — and skipped with
a log line. It is the one place the design lets the model judge values, and it is held
to the same discipline as everything else: the model sees the administrator's
instruction and the named values the administrator listed, nothing else, and answers
pass, fail or review. Code decides what each verdict becomes and sets the severity.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from greenlight_ai.checks.definitions import AdminConfig, CheckDefinition
from greenlight_ai.checks.named_values import NamedValue
from greenlight_ai.llm.client import LLMError
from greenlight_ai.pipeline.context import STAGE_ORDER, RunContext
from greenlight_ai.pipeline.run import run_pipeline

MakeContext = Callable[[str], RunContext]
THROUGH_7 = STAGE_ORDER[:7]

_VALUES = (
    NamedValue(name="billing_count", report_kind="billing", sheet="Summary", label="Billing count"),
    NamedValue(
        name="delivered_count", report_kind="billing", sheet="Summary", label="Delivered count"
    ),
)


def _judgment(value_names: tuple[str, ...] = ("billing_count", "delivered_count")) -> AdminConfig:
    return AdminConfig(
        checks=(
            CheckDefinition(
                id=5,
                name="volume_plausible",
                kind="judgment",
                instruction="The billed volume should be in line with the delivered volume.",
                value_names=value_names,
                reasoning="A billed count far from the delivered one means double counting.",
                severity="high",
            ),
        ),
        named_values=_VALUES,
    )


def _answer(verdict: str, reason: str = "Read against the rule.", confidence: float = 0.9) -> str:
    return json.dumps({"verdict": verdict, "reason": reason, "confidence": confidence})


def _answers(
    context: RunContext, verdict: str, reason: str = "Read.", confidence: float = 0.9
) -> None:
    context.client.register_text(  # type: ignore[attr-defined]
        "admin_judgment", _answer(verdict, reason, confidence)
    )


def _judged(context: RunContext) -> list[Any]:
    return [f for f in context.findings if f.type == "judgment_failed"]


def test_a_failing_judgment_is_a_finding_at_the_checks_severity(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _judgment()
    _answers(context, "fail", "Billed far exceeds delivered.")

    run_pipeline(context, stages=THROUGH_7)

    found = _judged(context)
    assert len(found) == 1
    assert found[0].severity == "high", "code sets the severity, from the check"
    assert found[0].rule_ref == "check:5"
    assert "Billed far exceeds delivered" in found[0].detail
    assert (
        "billing_count" in found[0].evidence.report_value
    ), "the values it judged are the evidence"


def test_a_passing_judgment_produces_nothing(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _judgment()
    _answers(context, "pass")

    run_pipeline(context, stages=THROUGH_7)

    assert not _judged(context)
    assert not [f for f in context.findings if f.type == "could_not_evaluate"]


def test_a_review_verdict_goes_to_a_person(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _judgment()
    _answers(context, "review", "No usual size was given.")

    run_pipeline(context, stages=THROUGH_7)

    found = _judged(context)
    assert len(found) == 1
    assert found[0].severity == "review"
    assert "needs a person" in found[0].title


def test_a_low_confidence_fail_is_review_not_high(make_context: MakeContext) -> None:
    """The model's own doubt never becomes a high finding; a person decides."""
    context = make_context("baseline_match")
    context.admin = _judgment()
    _answers(context, "fail", "Probably.", 0.3)

    run_pipeline(context, stages=THROUGH_7)

    found = _judged(context)
    assert len(found) == 1
    assert found[0].severity == "review"


def test_the_model_is_shown_only_the_values_the_check_names(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _judgment(value_names=("billing_count",))
    seen: list[str] = []

    def capture(system: str, user: str) -> str:
        seen.append(user)
        return _answer("pass")

    context.client.register("admin_judgment", capture)  # type: ignore[attr-defined]

    run_pipeline(context, stages=THROUGH_7)

    assert seen, "the check ran"
    prompt = seen[-1]
    assert "billing_count = " in prompt
    assert (
        "delivered_count" not in prompt.split("Now answer for this rule.")[-1]
    ), "a value the check did not list is not shown"
    assert "Summary" not in prompt.split("Now answer for this rule.")[-1], "never a sheet or a row"


def test_a_value_that_cannot_be_resolved_is_could_not_evaluate(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _judgment(value_names=("billing_count", "ghost_value"))
    _answers(context, "fail")

    run_pipeline(context, stages=THROUGH_7)

    assert not _judged(context), "no judgment was asked for"
    unresolved = [f for f in context.findings if f.type == "could_not_evaluate"]
    assert unresolved and "ghost_value" in unresolved[0].detail


def test_a_judgment_check_naming_no_values_says_so(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _judgment(value_names=())

    run_pipeline(context, stages=THROUGH_7)

    unresolved = [f for f in context.findings if f.type == "could_not_evaluate"]
    assert unresolved and "names no values" in unresolved[0].title


def test_a_model_that_does_not_answer_leaves_a_notice_not_a_pass(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _judgment()

    def explode(system: str, user: str) -> str:
        raise LLMError("gateway down")

    context.client.register("admin_judgment", explode)  # type: ignore[attr-defined]

    run_pipeline(context, stages=THROUGH_7)

    assert not _judged(context)
    assert any(
        "volume_plausible" in note for note in context.notices
    ), "silence would read as a pass, which is the one thing a check must not do"


def test_a_shadow_judgment_check_is_hidden(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    admin = _judgment()
    context.admin = AdminConfig(
        checks=admin.checks,
        named_values=admin.named_values,
        shadow_rule_refs=frozenset({"check:5"}),
    )
    _answers(context, "fail")

    run_pipeline(context, stages=THROUGH_7)

    found = _judged(context)
    assert len(found) == 1 and found[0].shadow is True
