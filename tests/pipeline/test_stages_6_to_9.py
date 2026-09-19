"""Tests for stages 6 to 9 and the full nine-stage run."""

from __future__ import annotations

from typing import Callable

import pytest

from greenlight_ai.checks.definitions import AdminConfig, CheckDefinition, ComplianceRule
from greenlight_ai.checks.named_values import NamedValue
from greenlight_ai.llm import LLMResponseError
from greenlight_ai.pipeline.context import STAGE_ORDER, RunContext
from greenlight_ai.pipeline.run import run_pipeline
from greenlight_ai.pipeline.s8_verify import format_evidence
from greenlight_ai.pipeline.s9_summarize import format_findings
from greenlight_ai.rules.schema import Evidence, Finding

MakeContext = Callable[[str], RunContext]

THROUGH_7 = STAGE_ORDER[:7]


def _types(context: RunContext) -> list[str]:
    return [f.type for f in context.findings]


# --- stage 6: the scoped reverse pass -------------------------------------------------


def test_an_untraced_filter_is_reported_as_extra(make_context: MakeContext) -> None:
    """Filters are in the reverse-pass scope."""
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER[:6])
    extra = [f for f in context.findings if f.type == "extra_rule_in_config"]
    assert all(f.severity == "medium" for f in extra)


def test_technical_elements_are_never_reverse_checked(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER[:6])
    for finding in context.findings:
        assert "logging" not in finding.title
        assert "source" not in finding.title


def test_categories_that_are_switched_off_are_ignored(make_context: MakeContext) -> None:
    from greenlight_ai.checks.definitions import ReversePassCategory

    context = make_context("baseline_match")
    context.admin = AdminConfig(
        categories=(ReversePassCategory("Filters", ("filters", "rules"), checked=False),)
    )
    run_pipeline(context, stages=STAGE_ORDER[:6])
    assert [f for f in context.findings if f.type == "extra_rule_in_config"] == []


def test_a_missing_compliance_rule_is_high_severity(make_context: MakeContext) -> None:
    """Compliance rules must be present even when the OSL never mentions them."""
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        compliance_rules=(
            ComplianceRule(
                name="Opt-out list applied",
                json_path_contains="suppressions.optout",
                reasoning="Every prescreen delivery must apply the opt-out list.",
            ),
        )
    )
    run_pipeline(context, stages=STAGE_ORDER[:6])
    missing = [f for f in context.findings if "Opt-out" in f.title]
    assert len(missing) == 1
    assert missing[0].severity == "high"
    assert "opt-out list" in missing[0].detail.lower()


def test_a_present_compliance_rule_produces_no_finding(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        compliance_rules=(ComplianceRule(name="OFAC", json_path_contains="suppressions.ofac"),)
    )
    run_pipeline(context, stages=STAGE_ORDER[:6])
    assert not [f for f in context.findings if "OFAC" in f.title]


def test_compliance_rules_out_of_scope_are_skipped(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.customer = "Acme Card Services"
    context.admin = AdminConfig(
        compliance_rules=(
            ComplianceRule(
                name="Harbor only", json_path_contains="suppressions.frozen", scope="Harbor CU"
            ),
        )
    )
    run_pipeline(context, stages=STAGE_ORDER[:6])
    assert not [f for f in context.findings if "Harbor" in f.title]


def test_stage_6_makes_no_llm_call(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER[:5])
    before = len(context.client.call_log.records)  # type: ignore[attr-defined]
    run_pipeline(context, stages=("s6_reverse",))
    assert len(context.client.call_log.records) == before  # type: ignore[attr-defined]


# --- stage 7: report checks -------------------------------------------------------------


def test_a_state_outside_the_allowed_set_violates_the_rule(make_context: MakeContext) -> None:
    """The worked example's third leg: NV and TX appear in the distribution."""
    context = make_context("geography_extra_state")
    run_pipeline(context, stages=THROUGH_7)
    violations = [f for f in context.findings if f.type == "report_violates_rule"]
    assert violations
    detail = " ".join(f.detail for f in violations)
    assert "TX" in detail and "NV" in detail


def test_a_delivered_minimum_below_the_threshold_violates_the_rule(
    make_context: MakeContext,
) -> None:
    context = make_context("score_value_mismatch")
    run_pipeline(context, stages=THROUGH_7)
    violations = [
        f for f in context.findings if f.type == "report_violates_rule" and "SCORE" in f.detail
    ]
    assert violations
    assert violations[0].severity == "high"
    assert violations[0].leg == "osl_reports"


def test_a_missing_attribute_violates_the_rule(
    make_context: MakeContext, cases: dict[str, object]
) -> None:
    """The OSL and config ask for one more attribute than the reports carry."""
    context = make_context("attributes_missing_in_report")
    run_pipeline(context, stages=THROUGH_7)
    violations = [f for f in context.findings if "attribute" in f.title.lower()]
    assert violations
    detail = " ".join(f.detail for f in violations)
    assert "missing 1 requested attribute" in detail


def test_counts_that_do_not_reconcile_are_reported(make_context: MakeContext) -> None:
    context = make_context("counts_do_not_reconcile")
    run_pipeline(context, stages=THROUGH_7)
    breaks = [f for f in context.findings if f.type == "count_does_not_reconcile"]
    assert len(breaks) == 1
    assert "-588" in breaks[0].detail


def test_a_reconciling_case_reports_no_count_break(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=THROUGH_7)
    assert not [f for f in context.findings if f.type == "count_does_not_reconcile"]


def test_report_findings_point_at_the_cell(make_context: MakeContext) -> None:
    context = make_context("score_value_mismatch")
    run_pipeline(context, stages=THROUGH_7)
    violation = next(
        f for f in context.findings if f.type == "report_violates_rule" and f.evidence.report_cell
    )
    assert violation.evidence.report_name == "dirt"
    assert violation.evidence.report_sheet == "Attributes"
    assert violation.evidence.report_cell.startswith("A")


# --- stage 7: admin checks ----------------------------------------------------------------


def _billing_admin(expression: str, name: str = "billing_not_above_delivered") -> AdminConfig:
    return AdminConfig(
        checks=(
            CheckDefinition(
                name=name,
                expression=expression,
                reasoning="Billing must not exceed what was delivered.",
                severity="high",
            ),
        ),
        named_values=(
            NamedValue(
                name="billing_count",
                report_kind="billing",
                sheet="Summary",
                label="Billing count",
            ),
            NamedValue(
                name="delivered_count",
                report_kind="billing",
                sheet="Summary",
                label="Delivered count",
            ),
        ),
    )


def test_a_passing_admin_check_produces_no_finding(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _billing_admin("billing_count <= delivered_count")
    run_pipeline(context, stages=THROUGH_7)
    assert not [f for f in context.findings if f.type == "cross_report_disagreement"]


def test_a_failing_admin_check_names_its_inputs(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = _billing_admin("billing_count > delivered_count", name="impossible")
    run_pipeline(context, stages=THROUGH_7)
    failures = [f for f in context.findings if f.type == "cross_report_disagreement"]
    assert len(failures) == 1
    assert "billing_count =" in failures[0].detail
    assert failures[0].severity == "high"


def test_an_unresolvable_named_value_becomes_a_finding_not_a_skip(
    make_context: MakeContext,
) -> None:
    """docs/design.md: it never skips silently."""
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        checks=(CheckDefinition(name="ghost", expression="ghost_value > 1"),),
        named_values=(
            NamedValue(
                name="ghost_value", report_kind="billing", sheet="Summary", label="Not present"
            ),
        ),
    )
    run_pipeline(context, stages=THROUGH_7)
    unresolved = [f for f in context.findings if f.type == "could_not_evaluate"]
    assert unresolved
    assert "ghost_value" in unresolved[0].detail


def test_a_malformed_expression_becomes_a_finding(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = AdminConfig(checks=(CheckDefinition(name="bad", expression="1 +"),))
    run_pipeline(context, stages=THROUGH_7)
    assert [f for f in context.findings if f.type == "could_not_evaluate"]


def test_an_inactive_check_does_not_run(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.admin = AdminConfig(
        checks=(CheckDefinition(name="off", expression="1 == 2", is_active=False),)
    )
    run_pipeline(context, stages=THROUGH_7)
    assert not [f for f in context.findings if "off" in f.title]


def test_a_check_scoped_to_another_customer_does_not_run(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.customer = "Acme Card Services"
    context.admin = AdminConfig(
        checks=(CheckDefinition(name="other", expression="1 == 2", scope="Northwind Lending"),)
    )
    run_pipeline(context, stages=THROUGH_7)
    assert not [f for f in context.findings if "other" in f.title]


def test_stage_7_makes_no_llm_call(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER[:6])
    before = len(context.client.call_log.records)  # type: ignore[attr-defined]
    run_pipeline(context, stages=("s7_reports",))
    assert len(context.client.call_log.records) == before  # type: ignore[attr-defined]


# --- stage 8: verification --------------------------------------------------------------------


def test_an_agreed_finding_keeps_its_severity(make_context: MakeContext) -> None:
    context = make_context("score_value_mismatch")
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_verify", '{"agreed": true, "reason": "Confirmed.", "confidence": 0.95}'
    )
    run_pipeline(context, stages=STAGE_ORDER[:8])
    high = [f for f in context.findings if f.severity == "high"]
    assert high
    assert all(f.verified and f.verify_agreed for f in high)


def test_a_disputed_finding_is_downgraded_and_kept(make_context: MakeContext) -> None:
    """The model may reduce false positives; it must not be able to hide a problem."""
    context = make_context("score_value_mismatch")
    before = run_pipeline(make_context("score_value_mismatch"), stages=STAGE_ORDER[:7])
    high_before = len([f for f in before.findings if f.severity == "high"])

    context.client.register_text(  # type: ignore[attr-defined]
        "s8_verify", '{"agreed": false, "reason": "Misread.", "confidence": 0.8}'
    )
    run_pipeline(context, stages=STAGE_ORDER[:8])

    assert len(context.findings) == len(before.findings)
    assert not [f for f in context.findings if f.severity == "high"]
    downgraded = [f for f in context.findings if f.verify_agreed is False]
    assert len(downgraded) == high_before
    assert all(f.severity == "review" for f in downgraded)
    assert "Second opinion disagreed" in downgraded[0].detail


def test_only_high_severity_findings_are_verified(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER[:8])
    for finding in context.findings:
        if finding.severity != "high":
            assert finding.verified is False


def test_a_verification_failure_leaves_the_finding_unchanged(make_context: MakeContext) -> None:
    """A second opinion is an improvement, not a gate."""

    def fail(_system: str, _user: str) -> str:
        raise LLMResponseError("the endpoint is down")

    context = make_context("score_value_mismatch")
    context.client.register("s8_verify", fail)  # type: ignore[attr-defined]
    run_pipeline(context, stages=STAGE_ORDER[:8])
    high = [f for f in context.findings if f.severity == "high"]
    assert high
    assert all(not f.verified for f in high)


def test_verify_evidence_carries_no_row_numbers() -> None:
    """ADR-003: the model does not need them and prompts never carry row data."""
    rendered = format_evidence(
        Evidence(
            osl_ref="OSL section 4",
            osl_text="at least 755",
            config_path="rules.score",
            config_value="750",
            report_name="dirt",
            report_sheet="Attributes",
            report_cell="D14",
            report_value="750",
            sample_rows=(3, 57, 212),
        )
    )
    assert "OSL section 4" in rendered
    assert "rules.score" in rendered
    assert "D14" in rendered
    assert "3" not in rendered.replace("755", "").replace("750", "")


def test_verify_evidence_handles_an_empty_record() -> None:
    assert "No structured evidence" in format_evidence(Evidence())


# --- stage 9: the summary -----------------------------------------------------------------------


def test_the_summary_is_written_from_the_findings(make_context: MakeContext) -> None:
    context = make_context("score_value_mismatch")
    context.client.register_text(  # type: ignore[attr-defined]
        "s9_summarize",
        '{"summary": "The score threshold is wrong.", "top_issues": ["Score 750 vs 755"]}',
    )
    run_pipeline(context, stages=STAGE_ORDER)
    assert context.summary == "The score threshold is wrong."
    assert context.top_issues == ("Score 750 vs 755",)


def test_the_summary_prompt_receives_findings_worst_first(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    context.findings = [
        Finding(finding_id="F-01", type="profile_anomaly", severity="low", title="low one"),
        Finding(finding_id="F-02", type="value_mismatch", severity="high", title="high one"),
        Finding(finding_id="F-03", type="extra_rule_in_config", severity="medium", title="mid"),
    ]
    rendered = format_findings(context)
    assert rendered.splitlines()[0].startswith("- high")
    assert rendered.splitlines()[-1].startswith("- low")


def test_an_empty_findings_list_is_stated_explicitly(make_context: MakeContext) -> None:
    """The prompt has a worked example for this case."""
    context = make_context("baseline_match")
    context.findings = []
    assert format_findings(context) == "(none)"


def test_a_summary_failure_does_not_fail_the_run(make_context: MakeContext) -> None:
    def fail(_system: str, _user: str) -> str:
        raise LLMResponseError("the endpoint is down")

    context = make_context("baseline_match")
    context.client.register("s9_summarize", fail)  # type: ignore[attr-defined]
    run_pipeline(context, stages=STAGE_ORDER)
    assert context.stages["s9_summarize"].status == "done"
    assert "could not be generated" in context.summary


# --- the whole pipeline ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("geography_extra_state", {"extra_rule_in_config", "report_violates_rule"}),
        ("score_value_mismatch", {"value_mismatch", "report_violates_rule"}),
        ("rule_missing_in_config", {"rule_missing_in_config"}),
        ("attributes_missing_in_report", {"report_violates_rule"}),
        ("counts_do_not_reconcile", {"count_does_not_reconcile"}),
    ],
)
def test_each_case_produces_the_findings_its_oracle_expects(
    make_context: MakeContext, case: str, expected: set[str]
) -> None:
    """The oracle travels with the fixture; this is the golden set's core assertion."""
    context = make_context(case)
    context.client.register_text(  # type: ignore[attr-defined]
        "s8_verify", '{"agreed": true, "reason": "Confirmed.", "confidence": 0.95}'
    )
    run_pipeline(context, stages=STAGE_ORDER)
    assert expected <= set(_types(context))


def test_the_clean_case_produces_no_serious_findings(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER)
    serious = [f for f in context.findings if f.severity in ("high", "medium")]
    assert serious == [], [f.title for f in serious]


def test_a_full_run_records_every_stage(make_context: MakeContext) -> None:
    context = make_context("baseline_match")
    run_pipeline(context, stages=STAGE_ORDER)
    assert all(context.stages[s].status == "done" for s in STAGE_ORDER)
    assert context.stages["s6_reverse"].llm_calls == 0
    assert context.stages["s7_reports"].llm_calls == 0
