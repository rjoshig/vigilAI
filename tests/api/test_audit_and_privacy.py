"""Audit completeness and log safety (Phase 6, ADR-003).

The audit log has to cover every action `phase-6.md` lists, and nothing anywhere may
carry a sample row.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from vigilai.db import models
from vigilai.worker.app import Worker

Submit = Callable[..., Any]


class _FakePdf:
    def render(self, html_path: Path, pdf_path: Path) -> Path:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.7")
        return pdf_path


def _actions(factory: sessionmaker[Session]) -> set[str]:
    with factory() as session:
        return set(session.execute(sa.select(models.AuditLog.action)).scalars())


def test_every_action_phase_6_lists_is_audited(
    submit: Submit, worker: Worker, client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Report view, download, review decision, requirement edit, rerun reason."""
    client.app.state.pdf_renderer = _FakePdf()  # type: ignore[attr-defined]

    run_id = submit("geography_extra_state").json()["run_id"]
    worker.run_once()

    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    for finding in findings:
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "false_positive", "review_note": "reviewed"},
        )

    requirements = client.get(f"{api}/runs/{run_id}/requirements").json()
    target = requirements["rules"][0]
    client.put(
        f"{api}/runs/{run_id}/requirements",
        json={"edits": [{"rule_id": target["rule_id"], "reason": "checking the audit log"}]},
    )
    worker.run_once()

    client.post(f"{api}/runs/{run_id}/finalize")
    client.get(f"{api}/runs/{run_id}/report")
    client.get(f"{api}/runs/{run_id}/report.pdf")

    submit("geography_extra_state")  # blocked as a duplicate
    submit("geography_extra_state", rerun_reason="a check was added")

    assert {
        "run.created",
        "run.completed",
        "run.duplicate_blocked",
        "run.requirements_edited",
        "run.rechecked",
        "finding.reviewed",
        "run.finalized",
        "report.viewed",
        "report.pdf_downloaded",
    } <= _actions(factory)


def test_admin_changes_are_audited(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    client.post(f"{api}/admin/aliases", json={"canonical_name": "score", "alias": "SCORE_V3"})
    client.post(f"{api}/admin/masked-columns", json={"pattern": "ACCT_REF"})
    client.post(
        f"{api}/admin/compliance-rules",
        json={"name": "OFAC", "json_path_contains": "suppressions.ofac"},
    )
    assert {
        "admin.alias_added",
        "admin.masked_column_added",
        "admin.compliance_saved",
    } <= _actions(factory)


#: Values that only ever appear inside a DIRT sample row. A configuration id like
#: CFG-SYNTH-GEO-02 is an *id*, which ADR-003 explicitly permits in logs; these are the
#: row contents, which it does not.
SAMPLE_ROW_VALUES = ("SYNTH1", "SYNTH2", "SYNTH3", "SYNTH4")


def test_the_audit_log_carries_no_file_content(
    submit: Submit, worker: Worker, factory: sessionmaker[Session]
) -> None:
    """ADR-003: ids and counts only."""
    submit("geography_extra_state")
    worker.run_once()
    with factory() as session:
        details = list(session.execute(sa.select(models.AuditLog.detail)).scalars())
    for detail in details:
        for value in SAMPLE_ROW_VALUES:
            assert value not in detail
        assert len(detail) < 200


def test_no_log_line_carries_a_sample_row(
    submit: Submit, worker: Worker, caplog: pytest.LogCaptureFixture
) -> None:
    """Logs carry ids and counts; a row value in one would outlive the run."""
    with caplog.at_level(logging.DEBUG, logger="vigilai"):
        submit("geography_extra_state")
        worker.run_once()
    text = "\n".join(record.getMessage() for record in caplog.records)
    for value in SAMPLE_ROW_VALUES:
        assert value not in text, f"a sample row value reached the log: {value}"
    for banned in ("123-45-6789", "@example.com"):
        assert banned not in text


def test_prompt_logging_is_off_by_default() -> None:
    """LLM_LOG_PROMPTS exists for synthetic data on a developer machine only."""
    from vigilai.llm.settings import LLMSettings

    assert LLMSettings().log_prompts is False
    assert LLMSettings.from_env({}).log_prompts is False


def test_turning_prompt_logging_on_warns_loudly(caplog: pytest.LogCaptureFixture) -> None:
    """A deployment that leaves it on should see it in the log every call."""
    from vigilai.llm import LLMSettings, MockClient

    client = MockClient(LLMSettings(log_prompts=True))
    with caplog.at_level(logging.WARNING, logger="vigilai.llm.base"):
        client.complete("system", "score at least 755", stage="s9_summarize")
    assert any("LLM_LOG_PROMPTS is on" in record.getMessage() for record in caplog.records)
