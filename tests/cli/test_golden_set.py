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
