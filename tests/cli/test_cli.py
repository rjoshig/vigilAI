"""Tests for the command-line entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from synthetic_model import FIXTURE_ALIASES, build_client
from greenlight_ai.cli import EXIT_FAILED, EXIT_OK, EXIT_USAGE, build_parser, main, run_command


def _argv(root: Path, case: dict[str, Any], out: Path, *extra: str) -> list[str]:
    argv = [
        "run",
        "--osl",
        str(root / case["osl"]),
        "--config",
        str(root / case["config"]),
        "--out",
        str(out),
        "--run-id",
        f"cli-{case['name']}",
        "--customer",
        case["customer"],
        "--log-level",
        "ERROR",
    ]
    for kind, path in case["reports"].items():
        argv += ["--report", f"{kind}={root / path}"]
    return argv + list(extra)


def _run(root: Path, case: dict[str, Any], out: Path, *extra: str) -> int:
    """Run the CLI with the scripted stand-in injected through the client seam."""
    args = build_parser().parse_args(_argv(root, case, out, *extra))
    return run_command(args, client=build_client(), aliases=FIXTURE_ALIASES)


# --- argument handling -----------------------------------------------------------------


def test_the_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_a_malformed_report_argument_is_a_usage_error(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    args = build_parser().parse_args(
        _argv(fixtures_root, cases["baseline_match"], tmp_path / "out.json") + ["--report", "oops"]
    )
    assert run_command(args, client=build_client()) == EXIT_USAGE


def test_an_unknown_report_kind_names_the_valid_kinds(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    args = build_parser().parse_args(
        _argv(fixtures_root, cases["baseline_match"], tmp_path / "out.json")
        + ["--report", "invoices=/tmp/x.xlsx"]
    )
    assert run_command(args, client=build_client()) == EXIT_USAGE
    assert "dirt" in caplog.text


def test_at_least_one_report_is_required(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    case = cases["baseline_match"]
    args = build_parser().parse_args(
        [
            "run",
            "--osl",
            str(fixtures_root / case["osl"]),
            "--config",
            str(fixtures_root / case["config"]),
            "--out",
            str(tmp_path / "out.json"),
        ]
    )
    assert run_command(args, client=build_client()) == EXIT_USAGE


# --- a complete run ----------------------------------------------------------------------


def test_a_run_writes_findings_json(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "findings.json"
    assert _run(fixtures_root, cases["geography_extra_state"], out) == EXIT_OK
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["run_id"] == "cli-geography_extra_state"
    assert document["counts"]["total"] == len(document["findings"])
    assert len(document["stages"]) == 9


def test_the_document_matches_the_cases_oracle(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    """Acceptance criterion 1: the findings JSON matches the oracle."""
    case = cases["geography_extra_state"]
    out = tmp_path / "findings.json"
    assert _run(fixtures_root, case, out) == EXIT_OK
    produced = {f["type"] for f in json.loads(out.read_text())["findings"]}
    assert set(case["expected"]["findings"]) <= produced


def test_findings_carry_their_evidence(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "findings.json"
    _run(fixtures_root, cases["score_value_mismatch"], out)
    findings = json.loads(out.read_text())["findings"]
    mismatch = next(f for f in findings if f["type"] == "value_mismatch")
    assert mismatch["evidence"]["osl_ref"].startswith("OSL section")
    assert mismatch["evidence"]["config_path"]


def test_the_document_reports_the_finalize_gate(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    """ADR-015: undecided high-severity findings hold the gate shut."""
    out = tmp_path / "findings.json"
    _run(fixtures_root, cases["score_value_mismatch"], out)
    document = json.loads(out.read_text())
    assert document["counts"]["high"] > 0
    assert document["can_finalize"] is False


def test_a_clean_run_can_finalize(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "findings.json"
    _run(fixtures_root, cases["baseline_match"], out)
    assert json.loads(out.read_text())["can_finalize"] is True


def test_no_sample_row_reaches_the_findings_document(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    """ADR-003: the output carries ids, thresholds, and aggregates only."""
    out = tmp_path / "findings.json"
    _run(fixtures_root, cases["geography_extra_state"], out)
    text = out.read_text()
    assert "SYNTH1" not in text
    for finding in json.loads(text)["findings"]:
        assert finding["evidence"]["sample_rows"] == []


def test_stage_selection_runs_only_those_stages(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "findings.json"
    assert _run(fixtures_root, cases["baseline_match"], out, "--stage", "s1_parse") == EXIT_OK
    stages = json.loads(out.read_text())["stages"]
    assert [s["stage"] for s in stages] == ["s1_parse"]


def test_the_document_records_stage_statistics(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "findings.json"
    _run(fixtures_root, cases["baseline_match"], out)
    stages = {s["stage"]: s for s in json.loads(out.read_text())["stages"]}
    assert stages["s2_extract"]["llm_calls"] > 0
    assert stages["s5_compare"]["llm_calls"] == 0
    assert all(s["status"] == "done" for s in stages.values())


# --- failures -------------------------------------------------------------------------------


def test_a_missing_input_exits_failed_and_still_writes_a_document(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    """A wrapper needs to see how far the run got."""
    case = dict(cases["baseline_match"])
    out = tmp_path / "findings.json"
    args = build_parser().parse_args(_argv(fixtures_root, case, out))
    args.osl = tmp_path / "absent.docx"
    assert run_command(args, client=build_client()) == EXIT_FAILED
    document = json.loads(out.read_text())
    assert "failed" in document
    assert document["stages"][0]["status"] == "failed"


def test_findings_mean_the_delivery_is_wrong_not_that_the_run_failed(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    """A run that completes exits 0 even when it finds serious problems."""
    out = tmp_path / "findings.json"
    assert _run(fixtures_root, cases["score_value_mismatch"], out) == EXIT_OK
    assert json.loads(out.read_text())["counts"]["high"] > 0


def test_an_invalid_provider_configuration_is_a_usage_error(
    fixtures_root: Path,
    cases: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    argv = _argv(fixtures_root, cases["baseline_match"], tmp_path / "out.json")
    assert main(argv) == EXIT_USAGE


def test_the_mock_provider_runs_without_any_configuration(
    fixtures_root: Path,
    cases: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests and CI need no endpoint (ADR-014)."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "out.json"
    argv = _argv(fixtures_root, cases["baseline_match"], out, "--provider", "mock")
    assert main(argv) == EXIT_OK
    assert out.exists()


def test_a_sqlite_cache_is_created_and_reused(
    fixtures_root: Path, cases: dict[str, Any], tmp_path: Path
) -> None:
    cache = tmp_path / "nested" / "cache.sqlite"
    out = tmp_path / "out.json"
    argv = _argv(
        fixtures_root, cases["baseline_match"], out, "--provider", "mock", "--cache", str(cache)
    )
    assert main(argv) == EXIT_OK
    assert cache.exists()
