"""Tests for the golden-set harness.

The golden set is the accuracy benchmark that runs whenever a prompt or the model
changes, so the harness itself needs to be trustworthy: a scorer that cannot detect a
regression is worse than none.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from golden_set import CaseScore, main, per_type, render, score_all


@pytest.fixture()
def scores(fixtures_root: Path, manifest: dict[str, Any]) -> list[CaseScore]:
    return score_all(manifest, fixtures_root, "synthetic", None)


def test_the_golden_set_covers_every_finding_type_the_design_doc_lists(
    manifest: dict[str, Any],
) -> None:
    expected = {kind for case in manifest["cases"] for kind in case["expected"]["findings"]}
    assert expected >= {
        "rule_missing_in_config",
        "extra_rule_in_config",
        "value_mismatch",
        "operator_mismatch",
        "waterfall_order_mismatch",
        "report_violates_rule",
        "count_does_not_reconcile",
    }


def test_the_golden_set_has_at_least_ten_cases(manifest: dict[str, Any]) -> None:
    """docs/phase-2.md 2f: 10 to 20 synthetic OSLs with known rules."""
    assert len(manifest["cases"]) >= 10


def test_every_case_meets_its_oracle(scores: list[CaseScore]) -> None:
    failures = [
        (s.name, sorted(s.false_negatives), sorted(s.false_positives))
        for s in scores
        if not s.passed
    ]
    assert failures == []


def test_no_case_raises_a_spurious_serious_finding(scores: list[CaseScore]) -> None:
    for score in scores:
        assert score.false_positives == frozenset()


def test_the_clean_case_produces_no_expected_findings(scores: list[CaseScore]) -> None:
    baseline = next(s for s in scores if s.name == "baseline_match")
    assert baseline.expected == frozenset()
    assert baseline.passed


def test_per_type_aggregation_counts_each_case(scores: list[CaseScore]) -> None:
    totals = per_type(scores)
    assert totals["report_violates_rule"]["expected"] >= 1
    assert totals["report_violates_rule"]["missed"] == 0


def test_the_report_names_the_provider_and_the_headline_numbers(scores: list[CaseScore]) -> None:
    report = render(scores, "synthetic", "n/a")
    assert "Provider: `synthetic`" in report
    assert "Recall" in report and "Precision" in report
    assert f"{len(scores)}** met their oracle" in report


def test_a_missed_finding_is_reported_as_a_failure() -> None:
    """The scorer must be able to fail; a scorer that always passes is worthless."""
    missed = CaseScore(
        name="regressed",
        expected=frozenset({"value_mismatch"}),
        produced=frozenset(),
        true_positives=frozenset(),
        false_negatives=frozenset({"value_mismatch"}),
        false_positives=frozenset(),
    )
    assert not missed.passed
    assert "fail" in render([missed], "synthetic", "n/a")


def test_a_spurious_finding_is_reported_as_a_failure() -> None:
    spurious = CaseScore(
        name="noisy",
        expected=frozenset(),
        produced=frozenset({"value_mismatch"}),
        true_positives=frozenset(),
        false_negatives=frozenset(),
        false_positives=frozenset({"value_mismatch"}),
    )
    assert not spurious.passed


def test_a_run_that_did_not_complete_is_reported_separately() -> None:
    errored = CaseScore(
        name="broken",
        expected=frozenset(),
        produced=frozenset(),
        true_positives=frozenset(),
        false_negatives=frozenset(),
        false_positives=frozenset(),
        error="s1_parse: file does not exist",
    )
    report = render([errored], "synthetic", "n/a")
    assert not errored.passed
    assert "did not complete" in report


def test_the_harness_exits_zero_when_every_case_passes(fixtures_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "phase-2.md"
    assert main(["--fixtures", str(fixtures_root), "--out", str(out)]) == 0
    assert "Golden set results" in out.read_text()


def test_the_harness_writes_a_markdown_report(fixtures_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "report.md"
    main(["--fixtures", str(fixtures_root), "--out", str(out)])
    body = out.read_text()
    assert body.startswith("# Golden set results")
    assert "| Finding type |" in body


def test_the_oracle_travels_with_the_fixture(manifest: dict[str, Any]) -> None:
    """No second file to drift out of step with the generator."""
    for case in manifest["cases"]:
        assert "findings" in case["expected"]
        assert isinstance(case["expected"]["findings"], list)


# --- what the benchmark measures beyond findings (Phase 6.11b) --------------------------


def test_coverage_is_scored_beside_precision_and_recall(scores: list[CaseScore]) -> None:
    """A run that finds nothing because it compared nothing must not score perfectly."""
    assert all(s.coverage_matches for s in scores), [
        (s.name, s.unevidenced, s.expected_unevidenced) for s in scores if not s.coverage_matches
    ]
    assert any(s.requirements for s in scores), "coverage counts reach the score"


def test_one_case_leaves_a_requirement_no_report_evidences(scores: list[CaseScore]) -> None:
    """The case the golden set had no example of until this phase."""
    case = next(s for s in scores if s.name == "unevidenced_requirement")

    assert case.expected == frozenset(), "its findings list is meant to be empty"
    assert case.unevidenced == 1
    assert case.checked < case.requirements


def test_one_case_delivers_a_report_no_check_examines(scores: list[CaseScore]) -> None:
    case = next(s for s in scores if s.name == "report_nothing_checks")

    assert "segment_summary" in case.unchecked_reports


def test_one_case_produces_a_low_severity_finding(scores: list[CaseScore]) -> None:
    """Nothing exercised the low-severity path before, which hid the bulk-OK defect."""
    case = next(s for s in scores if s.name == "credit_date_not_in_reports")

    assert "credit_date_missing" in case.expected
    assert case.passed


def test_cases_carry_a_programme_so_the_numbers_break_down(scores: list[CaseScore]) -> None:
    """The rollout gates are per programme, so the benchmark is too."""
    from golden_set import per_programme

    grouped = per_programme(scores)

    assert set(grouped) > {"(none)"}, "at least one case names a programme"
    assert sum(counts["cases"] for counts in grouped.values()) == len(scores)


def test_the_report_carries_coverage_and_the_programme_table(scores: list[CaseScore]) -> None:
    report = render(scores, "synthetic", "n/a")

    assert "Coverage:" in report
    assert "## Per programme" in report
    assert "Reports with no check" in report


def test_the_report_names_the_variant_it_ran(scores: list[CaseScore]) -> None:
    """Two reports that do not say which variant produced them cannot be compared."""
    single = render(scores, "synthetic", "n/a", ("single",))
    lenses = render(scores, "synthetic", "n/a", ("delivery", "compliance", "requirements"))

    assert "lenses: `single`" in single
    assert "lenses: `delivery,compliance,requirements`" in lenses


def test_coverage_that_does_not_match_the_oracle_fails_the_case() -> None:
    """A case that starts checking less than it did is a regression no finding shows."""
    score = CaseScore(
        name="drifted",
        expected=frozenset(),
        produced=frozenset(),
        true_positives=frozenset(),
        false_negatives=frozenset(),
        false_positives=frozenset(),
        unevidenced=3,
        expected_unevidenced=0,
    )

    assert score.passed, "its findings are right"
    assert not score.coverage_matches, "and it still must not be reported as clean"
    assert "Coverage does not match the oracle" in render([score], "synthetic", "n/a")
