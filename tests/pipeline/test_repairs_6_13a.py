"""The pipeline-side repairs of Phase 6.13a.

Each test here failed on ``dev`` before the repair it names. None of these defects was
visible: a rule that never runs looks exactly like a rule with nothing to say, and a
prompt that quietly loses a sentence still returns an answer.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from greenlight_ai.checks.definitions import AdminConfig, ComplianceRule
from greenlight_ai.pipeline.context import STAGE_ORDER, RunContext
from greenlight_ai.pipeline.guidance import RunGuidance
from greenlight_ai.pipeline.run import run_pipeline
from greenlight_ai.pipeline.s8_verify import _delivery_summary

MakeContext = Callable[[str], RunContext]


def _compliance(context: RunContext, name: str) -> list[Any]:
    return [f for f in context.findings if name in f.title]


# --- D4 · D5: shadow compliance rules run, and their findings say which rule -------------


def test_a_shadow_compliance_rule_runs_and_its_finding_is_hidden(make_context: MakeContext) -> None:
    """ADR-021 promised shadow first for every learned rule; compliance rules broke it."""
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        compliance_rules=(
            ComplianceRule(
                id=7,
                state="shadow",
                is_active=False,
                name="Frozen list applied",
                json_path_contains="suppressions.frozen",
            ),
        ),
        shadow_rule_refs=frozenset({"compliance_rule:7"}),
    )

    run_pipeline(context, stages=STAGE_ORDER[:6])

    found = _compliance(context, "Frozen list")
    assert len(found) == 1, "a shadow rule runs"
    assert found[0].shadow is True, "and nobody sees what it found"
    assert found[0].rule_ref == "compliance_rule:7", "and its finding names it"


def test_an_active_compliance_finding_carries_its_rule_reference(
    make_context: MakeContext,
) -> None:
    """Without a reference no compliance rule ever had statistics."""
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        compliance_rules=(
            ComplianceRule(id=3, name="Opt-out list", json_path_contains="suppressions.optout"),
        )
    )

    run_pipeline(context, stages=STAGE_ORDER[:6])

    found = _compliance(context, "Opt-out")
    assert found and found[0].rule_ref == "compliance_rule:3"
    assert found[0].shadow is False


# --- D14: the expected value is compared, not just the path's presence -------------------


def test_a_flag_set_to_the_wrong_value_is_a_finding(make_context: MakeContext) -> None:
    """The baseline configuration sets ``suppressions.deceased`` to true."""
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        compliance_rules=(
            ComplianceRule(
                id=1,
                name="Deceased suppression off",
                json_path_contains="suppressions.deceased",
                expected_value=False,
            ),
        )
    )

    run_pipeline(context, stages=STAGE_ORDER[:6])

    found = _compliance(context, "Deceased suppression off")
    assert len(found) == 1
    assert found[0].type == "value_mismatch"
    assert found[0].evidence.config_path == "suppressions.deceased"
    assert "True" in found[0].evidence.config_value


def test_a_flag_set_to_the_expected_value_passes(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        compliance_rules=(
            ComplianceRule(
                id=1,
                name="Deceased suppression on",
                json_path_contains="suppressions.deceased",
                expected_value=True,
            ),
        )
    )

    run_pipeline(context, stages=STAGE_ORDER[:6])

    assert not _compliance(context, "Deceased suppression on")


def test_a_structure_at_the_path_is_presence_only(make_context: MakeContext) -> None:
    """``rules.age`` holds an object; "true" against an object means nothing."""
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        compliance_rules=(
            ComplianceRule(
                id=1, name="Age rule", json_path_contains="rules.age", expected_value=False
            ),
        )
    )

    run_pipeline(context, stages=STAGE_ORDER[:6])

    assert not _compliance(context, "Age rule"), "presence satisfies a rule over a structure"


# --- D6: a shadow programme rule is shadowed -----------------------------------------------


def test_a_shadow_programme_rule_produces_a_hidden_finding(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.guidance = RunGuidance(
        scope_code="AM",
        scope_label="Account Monitoring",
        programme_rules=((11, "Two-state limit", "Deliver only two states.", "must"),),
    )
    context.admin = AdminConfig(shadow_rule_refs=frozenset({"programme_rule:11"}))
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_programme",
        json.dumps(
            {
                "breaches": [
                    {
                        "rule_id": 11,
                        "evidence": "three states appear",
                        "reason": "A third state is delivered.",
                        "confidence": 0.9,
                    }
                ]
            }
        ),
    )

    run_pipeline(context, stages=STAGE_ORDER[:8])

    breaches = [f for f in context.findings if f.type == "programme_rule_violation"]
    assert len(breaches) == 1
    assert breaches[0].shadow is True, "a shadow programme rule interrupted reviewers before"
    assert breaches[0].rule_ref == "programme_rule:11"


# --- D7: the programme read sees the requirement's wording --------------------------------


def test_the_programme_read_is_given_the_osl_wording(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER[:2])
    worded = [rule for rule in context.rules if rule.source_text.strip()]
    assert worded, "the fixture's requirements carry their source sentence"

    summary = _delivery_summary(context)

    assert worded[0].source_text.strip()[:40] in summary
    assert "criteria: ()" not in summary, "the old fallback rendered an empty tuple"


# --- D8: AI context written on a report type reaches the verification of that report -----


def test_report_ai_context_reaches_the_lens_that_reads_that_report(
    make_context: MakeContext,
) -> None:
    context = make_context("geography_extra_state")
    context.guidance = RunGuidance(
        artifact_context={"state_distribution": "The second tab of this workbook is a reissue."}
    )
    seen: list[str] = []

    def capture(system: str, user: str) -> str:
        seen.append(user)
        return json.dumps({"agreed": True, "reason": "Confirmed.", "confidence": 0.9})

    context.client.register("s8_verify", capture)  # type: ignore[attr-defined]

    run_pipeline(context, stages=STAGE_ORDER[:8])

    about_the_report = [
        f for f in context.findings if f.severity == "high" and f.evidence.report_name
    ]
    assert about_the_report, "the fixture raises a high finding about a report"
    assert any(
        "second tab of this workbook" in prompt for prompt in seen
    ), "the report's own context reached no prompt at all before 6.13a"
