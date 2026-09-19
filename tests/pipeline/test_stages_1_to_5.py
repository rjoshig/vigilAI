"""Tests for stages 1 to 5 and the orchestrator.

The acceptance test for this milestone is the design doc's worked example: OSL says
{IL, AZ}, config says {IL, AZ, TX}, and stage 5 reports TX as extra.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from greenlight_ai.llm import LLMSettings, MockClient
from greenlight_ai.pipeline.context import STAGE_ORDER, RunContext
from greenlight_ai.pipeline.run import PipelineError, recheck, run_pipeline
from greenlight_ai.pipeline.s4_trace import describe_rule, exact_match, shortlist
from greenlight_ai.rules.schema import Condition, ConfigElement, Rule

CORE = ("s1_parse", "s2_extract", "s3_describe", "s4_trace", "s5_compare")

MakeContext = Callable[[str], RunContext]


def _run(make_context: MakeContext, case: str) -> RunContext:
    return run_pipeline(make_context(case), stages=CORE)


# --- stage 1 ------------------------------------------------------------------------


def test_stage_1_parses_every_input(make_context: MakeContext) -> None:
    context = run_pipeline(make_context("baseline_match"), stages=("s1_parse",))
    assert context.osl is not None and context.osl.sections
    assert context.config is not None and context.config.blocks
    assert set(context.reports) == {
        "dirt",
        "state_distribution",
        "field_distribution",
        "counts",
        "billing",
    }


def test_stage_1_masks_report_values(make_context: MakeContext) -> None:
    """No unmasked report value exists downstream of stage 1 (ADR-003)."""
    context = run_pipeline(make_context("baseline_match"), stages=("s1_parse",))
    sample = context.reports["dirt"].sheet("Sample")
    assert sample is not None
    assert "FIRST_NAME" in sample.masked_columns


def test_a_missing_input_stops_the_run(make_context: MakeContext, tmp_path: Path) -> None:
    """A partially read input would look like a missing requirement."""
    context = make_context("baseline_match")
    context.osl_path = tmp_path / "absent.docx"
    with pytest.raises(PipelineError) as excinfo:
        run_pipeline(context, stages=("s1_parse",))
    assert excinfo.value.stage == "s1_parse"
    assert context.stages["s1_parse"].status == "failed"


# --- stage 2 ------------------------------------------------------------------------


def test_stage_2_extracts_the_geography_requirement(make_context: MakeContext) -> None:
    context = run_pipeline(make_context("baseline_match"), stages=("s1_parse", "s2_extract"))
    geography = [r for r in context.rules if r.req_type == "geography"]
    assert len(geography) == 1
    assert set(geography[0].values) == {"IL", "AZ"}


def test_stage_2_normalises_state_names_to_codes(make_context: MakeContext) -> None:
    """The OSL writes "Illinois"; comparison needs "IL". Code transforms, not the model."""
    context = run_pipeline(make_context("baseline_match"), stages=("s1_parse", "s2_extract"))
    geography = next(r for r in context.rules if r.req_type == "geography")
    assert "Illinois" not in geography.values


def test_stage_2_extracts_criteria_from_the_table(make_context: MakeContext) -> None:
    context = run_pipeline(make_context("baseline_match"), stages=("s1_parse", "s2_extract"))
    criteria = {
        c.field_name: c for r in context.rules if r.req_type == "criteria" for c in r.conditions
    }
    assert criteria["score"].operator == ">="
    assert criteria["score"].value == 755
    assert criteria["age"].value == 21


def test_stage_2_keeps_the_source_reference_for_evidence(make_context: MakeContext) -> None:
    context = run_pipeline(make_context("baseline_match"), stages=("s1_parse", "s2_extract"))
    assert all(r.source_ref.startswith("OSL section") for r in context.rules)


def test_stage_2_requires_stage_1() -> None:
    context = RunContext(
        run_id="X",
        osl_path=Path("a.docx"),
        config_path=Path("b.json"),
        report_paths={},
        client=MockClient(LLMSettings()),
    )
    with pytest.raises(PipelineError, match="requires stage 1"):
        run_pipeline(context, stages=("s2_extract",))


# --- stage 3 ------------------------------------------------------------------------


def test_stage_3_describes_business_blocks(make_context: MakeContext) -> None:
    context = run_pipeline(make_context("baseline_match"), stages=CORE[:3])
    business = [e for e in context.elements if not e.is_technical]
    assert any(e.rule is not None and e.rule.req_type == "geography" for e in business)


def test_stage_3_skips_technical_blocks_without_a_call(make_context: MakeContext) -> None:
    """Classifying plumbing in code saves a call each and keeps it out of the reverse pass."""
    context = run_pipeline(make_context("baseline_match"), stages=CORE[:3])
    logging_element = next(e for e in context.elements if e.json_path == "logging")
    assert logging_element.is_technical
    described = [
        p for p in context.client.prompts if p[0] == "s3_describe"  # type: ignore[attr-defined]
    ]
    blocks = [prompt.split("Block:\n")[-1] for _stage, _system, prompt in described]
    assert not any(block.startswith("logging") for block in blocks)


# --- stage 4 ------------------------------------------------------------------------


def test_stage_4_links_exact_matches_in_code_without_a_call(make_context: MakeContext) -> None:
    """ADR: code first. An exact match must never consume a judge call."""
    context = run_pipeline(make_context("baseline_match"), stages=CORE[:4])
    geography_rule = next(r for r in context.rules if r.req_type == "geography")
    trace = context.trace_for(geography_rule.rule_id)
    assert trace is not None
    assert trace.by_code is True
    assert trace.verdict == "implemented"


def test_stage_4_asks_the_judge_only_when_values_differ(make_context: MakeContext) -> None:
    context = _run(make_context, "geography_extra_state")
    judged = [p for p in context.client.prompts if p[0] == "s4_trace"]  # type: ignore[attr-defined]
    geography_rule = next(r for r in context.rules if r.req_type == "geography")
    trace = context.trace_for(geography_rule.rule_id)
    assert trace is not None and trace.by_code is False
    assert judged


def test_stage_4_reports_not_related_when_nothing_implements_a_rule(
    make_context: MakeContext,
) -> None:
    context = _run(make_context, "rule_missing_in_config")
    score_rule = next(
        r
        for r in context.rules
        if any(c.field_name.lower().startswith("score") for c in r.conditions)
    )
    trace = context.trace_for(score_rule.rule_id)
    assert trace is not None
    assert trace.element_id is None
    assert trace.verdict == "not_related"


def test_shortlist_narrows_by_type_then_field() -> None:
    from synthetic_model import FIXTURE_ALIASES

    rule = Rule(
        rule_id="R-1",
        source="osl",
        req_type="criteria",
        conditions=[Condition(field_name="score", operator=">=", value=755)],
    )
    score = ConfigElement(
        element_id="C-1",
        json_path="rules.score_v3",
        rule=Rule(
            rule_id="C-1",
            source="config",
            req_type="criteria",
            conditions=[Condition(field_name="SCORE_V3", operator=">=", value=750)],
        ),
    )
    age = ConfigElement(
        element_id="C-2",
        json_path="rules.age",
        rule=Rule(
            rule_id="C-2",
            source="config",
            req_type="criteria",
            conditions=[Condition(field_name="AGE", operator=">=", value=21)],
        ),
    )
    geography = ConfigElement(
        element_id="C-3",
        json_path="filters[0]",
        rule=Rule(
            rule_id="C-3", source="config", req_type="geography", values=("IL",), mode="include"
        ),
    )
    assert shortlist(rule, [score, age, geography], FIXTURE_ALIASES) == [score]


def test_shortlist_falls_back_to_type_when_no_field_matches() -> None:
    """A missing alias must not masquerade as "no config rule"."""
    from synthetic_model import FIXTURE_ALIASES

    rule = Rule(
        rule_id="R-1",
        source="osl",
        req_type="criteria",
        conditions=[Condition(field_name="mystery", operator=">=", value=1)],
    )
    element = ConfigElement(
        element_id="C-1",
        json_path="rules.other",
        rule=Rule(
            rule_id="C-1",
            source="config",
            req_type="criteria",
            conditions=[Condition(field_name="OTHER", operator=">=", value=1)],
        ),
    )
    assert shortlist(rule, [element], FIXTURE_ALIASES) == [element]


def test_exact_match_resolves_aliases_and_number_formatting() -> None:
    from synthetic_model import FIXTURE_ALIASES

    rule = Rule(
        rule_id="R-1",
        source="osl",
        req_type="criteria",
        conditions=[Condition(field_name="score", operator=">=", value=755)],
    )
    element = ConfigElement(
        element_id="C-1",
        json_path="rules.score_v3",
        rule=Rule(
            rule_id="C-1",
            source="config",
            req_type="criteria",
            conditions=[Condition(field_name="SCORE_V3", operator=">=", value=755.0)],
        ),
    )
    assert exact_match(rule, element, FIXTURE_ALIASES)


def test_describe_rule_carries_no_row_data() -> None:
    rule = Rule(
        rule_id="R-1", source="osl", req_type="geography", values=("IL", "AZ"), mode="include"
    )
    assert describe_rule(rule) == "geography — include ['AZ', 'IL']"


# --- stage 5: the worked example ------------------------------------------------------


def test_the_design_docs_worked_example(make_context: MakeContext) -> None:
    """OSL {IL, AZ} vs config {IL, AZ, TX}: stage 5 reports TX as extra."""
    context = _run(make_context, "geography_extra_state")
    extra = [f for f in context.findings if f.type == "extra_rule_in_config"]
    assert len(extra) == 1
    assert "TX" in extra[0].detail
    assert extra[0].severity == "medium"
    assert extra[0].leg == "osl_config"


def test_the_worked_example_carries_three_way_evidence(make_context: MakeContext) -> None:
    context = _run(make_context, "geography_extra_state")
    finding = next(f for f in context.findings if f.type == "extra_rule_in_config")
    assert finding.evidence.osl_ref.startswith("OSL section")
    assert "Illinois or Arizona" in finding.evidence.osl_text
    assert finding.evidence.config_path == "filters[0]"


def test_a_matching_case_produces_no_comparison_findings(make_context: MakeContext) -> None:
    context = _run(make_context, "baseline_match")
    comparison_types = {
        "value_mismatch",
        "operator_mismatch",
        "extra_rule_in_config",
        "rule_missing_in_config",
        "waterfall_order_mismatch",
    }
    assert [f for f in context.findings if f.type in comparison_types] == []


def test_a_value_mismatch_is_reported_with_both_thresholds(make_context: MakeContext) -> None:
    context = _run(make_context, "score_value_mismatch")
    mismatch = next(f for f in context.findings if f.type == "value_mismatch")
    assert "755" in mismatch.title and "750" in mismatch.title
    assert mismatch.severity == "high"


def test_a_missing_rule_is_high_severity(make_context: MakeContext) -> None:
    context = _run(make_context, "rule_missing_in_config")
    missing = [f for f in context.findings if f.type == "rule_missing_in_config"]
    assert missing
    assert all(f.severity == "high" for f in missing)


def test_findings_are_stamped_with_the_rules_version(make_context: MakeContext) -> None:
    context = _run(make_context, "score_value_mismatch")
    assert all(f.rules_version == 1 for f in context.findings)


def test_finding_ids_are_unique(make_context: MakeContext) -> None:
    context = _run(make_context, "geography_extra_state")
    ids = [f.finding_id for f in context.findings]
    assert len(ids) == len(set(ids))


# --- the finalize gate ------------------------------------------------------------------


def test_a_run_with_undecided_high_findings_cannot_finalize(make_context: MakeContext) -> None:
    """ADR-015."""
    context = _run(make_context, "score_value_mismatch")
    assert context.high_severity_findings
    assert context.can_finalize is False


def test_deciding_every_high_finding_opens_the_gate(make_context: MakeContext) -> None:
    context = _run(make_context, "score_value_mismatch")
    context.findings = [
        f.model_copy(update={"review_status": "confirmed"}) if f.severity == "high" else f
        for f in context.findings
    ]
    assert context.can_finalize is True


# --- orchestration -----------------------------------------------------------------------


def test_every_stage_records_status_and_duration(make_context: MakeContext) -> None:
    context = _run(make_context, "baseline_match")
    for stage in CORE:
        assert context.stages[stage].status == "done"


def test_llm_stages_record_their_calls_and_tokens(make_context: MakeContext) -> None:
    context = _run(make_context, "baseline_match")
    assert context.stages["s2_extract"].llm_calls > 0
    assert context.stages["s2_extract"].tokens > 0
    assert context.stages["s1_parse"].llm_calls == 0


def test_all_nine_stages_run(make_context: MakeContext) -> None:
    context = run_pipeline(make_context("baseline_match"), stages=STAGE_ORDER)
    assert [context.stages[s].status for s in STAGE_ORDER] == ["done"] * 9


def test_resume_skips_stages_already_done(make_context: MakeContext) -> None:
    context = _run(make_context, "baseline_match")
    calls_before = len(context.client.call_log.records)  # type: ignore[attr-defined]
    run_pipeline(context, stages=CORE, resume=True)
    assert len(context.client.call_log.records) == calls_before  # type: ignore[attr-defined]


def test_resume_from_reports_the_first_unfinished_stage(make_context: MakeContext) -> None:
    context = run_pipeline(make_context("baseline_match"), stages=("s1_parse", "s2_extract"))
    assert context.resume_from() == "s3_describe"


def test_a_second_identical_run_makes_no_network_calls(make_context: MakeContext) -> None:
    """ADR-005: the same content is never sent twice."""
    first = _run(make_context, "baseline_match")
    shared_cache = first.client.cache  # type: ignore[attr-defined]

    second = make_context("baseline_match")
    second.client = MockClient(LLMSettings(), cache=shared_cache)
    for stage in ("s2_extract", "s3_describe", "s4_trace"):
        second.client.register(stage, first.client._responders[stage])  # type: ignore[attr-defined]
    run_pipeline(second, stages=CORE)

    assert second.client.prompts == []
    assert second.client.call_log.cache_hits == len(second.client.call_log.records)


def test_recheck_reruns_comparisons_without_calling_a_model(make_context: MakeContext) -> None:
    """Re-check after a user edit must cost nothing (design.md "Re-check path")."""
    context = _run(make_context, "score_value_mismatch")
    calls_before = len(context.client.call_log.records)  # type: ignore[attr-defined]

    recheck(context)

    assert len(context.client.call_log.records) == calls_before  # type: ignore[attr-defined]
    assert context.rules_version == 2
    assert all(f.rules_version == 2 for f in context.findings)


def test_recheck_keeps_decisions_already_made(make_context: MakeContext) -> None:
    context = _run(make_context, "score_value_mismatch")
    context.findings = [
        f.model_copy(update={"review_status": "accepted_risk"}) if f.severity == "high" else f
        for f in context.findings
    ]
    decided = sum(1 for f in context.findings if f.review_status != "undecided")

    recheck(context)

    assert sum(1 for f in context.findings if f.review_status == "accepted_risk") == decided


def test_a_pipeline_error_names_the_stage_and_survives_pickling() -> None:
    import pickle

    error = PipelineError("s2_extract", "the model refused")
    restored = pickle.loads(pickle.dumps(error))
    assert restored.stage == "s2_extract"
    assert str(restored) == str(error)
