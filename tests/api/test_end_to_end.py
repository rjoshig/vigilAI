"""End-to-end tests for the Phase 3 acceptance criteria.

These drive the real API and the real worker against a SQLite database (ADR-017), so
they prove the whole path without Docker: submit, queue, run, review, re-check.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.db.queue import JobQueue
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]


def _run_to_completion(worker: Worker, limit: int = 5) -> int:
    """Drive the worker until the queue is empty."""
    processed = 0
    for _ in range(limit):
        if not worker.run_once():
            break
        processed += 1
    return processed


def _add_low_finding(
    factory: sessionmaker[Session], run_id: int, title: str = "Null rate is high"
) -> int:
    """Give a run a low-severity finding.

    No fixture case produces one, so a test about the bulk action has to make one or it
    proves nothing: before Phase 6.11a the existing bulk test passed on zero rows.

    Args:
        factory: The test session factory.
        run_id: The run to attach it to.
        title: The finding's title.

    Returns:
        The new finding's row id.
    """
    with factory() as session:
        finding = models.Finding(
            run_id=run_id,
            finding_id="F-LOW-1",
            type="profile_anomaly",
            severity="low",
            title=title,
            detail="Null rate for a field is above its usual level.",
        )
        session.add(finding)
        session.commit()
        return int(finding.id)


def _clear_the_gate(client: TestClient, api: str, run_id: int) -> None:
    """Decide every finding the gate asks about and acknowledge every gap.

    The gate is ADR-035's: high and review findings decided, coverage gaps and
    unevaluated checks acknowledged. Tests that only want a finalized run say so in
    one line rather than repeating the sequence.

    Args:
        client: The test client.
        api: The API prefix.
        run_id: The run.
    """
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        if finding["severity"] in {"high", "review"}:
            client.patch(
                f"{api}/findings/{finding['id']}",
                json={"review_status": "false_positive", "review_note": "checked by hand"},
            )
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]
    if outstanding:
        client.post(
            f"{api}/runs/{run_id}/coverage/acknowledge",
            json={"targets": outstanding, "note": "seen"},
        )


@pytest.fixture()
def completed_run(submit: Submit, worker: Worker, client: TestClient, api: str) -> dict[str, Any]:
    """A run submitted through the API and executed by the worker."""
    run_id = submit("geography_extra_state").json()["run_id"]
    _run_to_completion(worker)
    return client.get(f"{api}/runs/{run_id}").json()


# --- criterion 1: queued → running → needs_review -----------------------------------------


def test_a_submitted_run_reaches_needs_review(completed_run: dict[str, Any]) -> None:
    assert completed_run["status"] == "needs_review"
    assert completed_run["error"] == ""


def test_every_stage_is_recorded_with_timings(completed_run: dict[str, Any]) -> None:
    stages = {s["stage"]: s for s in completed_run["stages"]}
    assert len(stages) == 9
    assert all(s["status"] == "done" for s in stages.values())
    assert stages["s2_extract"]["llm_calls"] > 0
    assert stages["s5_compare"]["llm_calls"] == 0


def test_the_run_records_which_model_answered(completed_run: dict[str, Any]) -> None:
    assert completed_run["model_used"]
    assert completed_run["prompt_version"]


def test_the_worked_example_produces_its_findings(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    findings = client.get(f"{api}/runs/{completed_run['id']}/findings").json()
    types = {f["type"] for f in findings}
    assert "extra_rule_in_config" in types
    assert "report_violates_rule" in types


def test_findings_come_back_worst_first(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    severities = [
        f["severity"] for f in client.get(f"{api}/runs/{completed_run['id']}/findings").json()
    ]
    order = {"high": 0, "medium": 1, "low": 2, "review": 3}
    assert severities == sorted(severities, key=lambda s: order[s])


def test_findings_carry_their_evidence(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    findings = client.get(f"{api}/runs/{completed_run['id']}/findings").json()
    violation = next(f for f in findings if f["type"] == "report_violates_rule")
    assert violation["evidence"]["osl_ref"].startswith("OSL section")


def test_no_sample_row_reaches_the_api(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    """ADR-003: the wire format carries aggregates, never row contents."""
    body = client.get(f"{api}/runs/{completed_run['id']}/findings").text
    assert "SYNTH1" not in body
    for finding in client.get(f"{api}/runs/{completed_run['id']}/findings").json():
        assert finding["evidence"].get("sample_rows", []) == []


def test_the_traceability_matrix_is_available(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    body = client.get(f"{api}/runs/{completed_run['id']}/requirements").json()
    assert body["rules"]
    assert body["traces"]
    assert all(rule["summary"] for rule in body["rules"])


def test_stats_report_calls_tokens_and_cache_hits(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    body = client.get(f"{api}/runs/{completed_run['id']}/stats").json()
    assert body["llm_calls"] > 0
    assert body["prompt_tokens"] > 0
    assert len(body["stages"]) == 9


# --- criterion 2: duplicates and rerun reasons ----------------------------------------


def test_the_cache_makes_a_rerun_free(
    submit: Submit, worker: Worker, client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """ADR-005: the same content is never sent to the model twice."""
    submit("baseline_match")
    _run_to_completion(worker)
    second = submit("baseline_match", rerun_reason="checking the cache").json()["run_id"]
    _run_to_completion(worker)

    stats = client.get(f"{api}/runs/{second}/stats").json()
    assert stats["llm_calls"] > 0
    assert stats["cache_hits"] == stats["llm_calls"]


# --- criterion 3: re-check is fast and free ------------------------------------------------------


def test_recheck_rebuilds_findings_without_calling_the_model(
    completed_run: dict[str, Any],
    worker: Worker,
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
) -> None:
    run_id = completed_run["id"]
    with factory() as session:
        before = int(
            session.execute(
                sa.select(sa.func.count())
                .select_from(models.LlmCall)
                .where(models.LlmCall.run_id == run_id, models.LlmCall.cached.is_(False))
            ).scalar_one()
        )

    assert client.post(f"{api}/runs/{run_id}/recheck").json()["queued"] is True
    _run_to_completion(worker)

    with factory() as session:
        after = int(
            session.execute(
                sa.select(sa.func.count())
                .select_from(models.LlmCall)
                .where(models.LlmCall.run_id == run_id, models.LlmCall.cached.is_(False))
            ).scalar_one()
        )
    assert after == before
    assert client.get(f"{api}/runs/{run_id}/findings").json()


def test_a_recheck_keeps_the_run_summary(
    completed_run: dict[str, Any],
    worker: Worker,
    client: TestClient,
    api: str,
) -> None:
    """A re-check rebuilds findings; it does not erase the account of the run.

    Stage 9 writes the plain-English summary and a re-check skips it, but
    ``save_context`` wrote ``context.summary`` unconditionally — so every re-check
    replaced the summary with the empty string the context was built with. The
    reviewer lost the narrative in the act of correcting one rule (Phase 6.23a).
    """
    run_id = completed_run["id"]
    before = client.get(f"{api}/runs/{run_id}").json()["summary"]
    assert before, "the fixture run should have a summary to lose"

    assert client.post(f"{api}/runs/{run_id}/recheck").json()["queued"] is True
    _run_to_completion(worker)

    assert client.get(f"{api}/runs/{run_id}").json()["summary"] == before


def test_editing_a_requirement_bumps_the_version_and_queues_a_recheck(
    completed_run: dict[str, Any], worker: Worker, client: TestClient, api: str
) -> None:
    run_id = completed_run["id"]
    requirements = client.get(f"{api}/runs/{run_id}/requirements").json()
    target = next(r for r in requirements["rules"] if r["req_type"] == "geography")

    edited = dict(target["rule"])
    edited["values"] = ["IL", "AZ", "TX"]
    response = client.put(
        f"{api}/runs/{run_id}/requirements",
        json={"edits": [{"rule_id": target["rule_id"], "rule": edited, "reason": "TX was agreed"}]},
    )
    assert response.status_code == 200
    assert response.json()["rules_version"] == requirements["rules_version"] + 1

    _run_to_completion(worker)
    after = client.get(f"{api}/runs/{run_id}/requirements").json()
    updated = next(r for r in after["rules"] if r["rule_id"] == target["rule_id"])
    assert set(updated["rule"]["values"]) == {"IL", "AZ", "TX"}
    assert updated["source"] == "user"


def test_editing_away_the_mismatch_removes_the_finding(
    completed_run: dict[str, Any], worker: Worker, client: TestClient, api: str
) -> None:
    """The point of an edit: correct the reading, and the finding should go."""
    run_id = completed_run["id"]
    requirements = client.get(f"{api}/runs/{run_id}/requirements").json()
    target = next(r for r in requirements["rules"] if r["req_type"] == "geography")
    edited = dict(target["rule"])
    edited["values"] = ["IL", "AZ", "TX"]

    client.put(
        f"{api}/runs/{run_id}/requirements",
        json={"edits": [{"rule_id": target["rule_id"], "rule": edited, "reason": "TX was agreed"}]},
    )
    _run_to_completion(worker)

    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    extra = [f for f in findings if f["type"] == "extra_rule_in_config"]
    assert extra == []


def test_an_invalid_edit_is_rejected(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    run_id = completed_run["id"]
    requirements = client.get(f"{api}/runs/{run_id}/requirements").json()
    target = next(r for r in requirements["rules"] if r["req_type"] == "geography")
    broken = dict(target["rule"])
    broken["values"] = []
    response = client.put(
        f"{api}/runs/{run_id}/requirements",
        json={"edits": [{"rule_id": target["rule_id"], "rule": broken}]},
    )
    assert response.status_code == 422


def test_editing_an_unknown_rule_is_a_404(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    response = client.put(
        f"{api}/runs/{completed_run['id']}/requirements",
        json={"edits": [{"rule_id": "R-999", "reason": "nope"}]},
    )
    assert response.status_code == 404


# --- review ---------------------------------------------------------------------------


def test_a_decision_is_recorded_and_opens_the_gate(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    """ADR-035: high and review findings decided, and every coverage gap acknowledged."""
    run_id = completed_run["id"]
    assert client.get(f"{api}/runs/{run_id}").json()["can_finalize"] is False

    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        if finding["severity"] == "high":
            response = client.patch(
                f"{api}/findings/{finding['id']}",
                json={"review_status": "confirmed", "review_note": "raised with the ETL team"},
            )
            assert response.status_code == 200
            assert response.json()["review_status"] == "confirmed"

    _clear_the_gate(client, api, run_id)
    assert client.get(f"{api}/runs/{run_id}").json()["can_finalize"] is True


def test_deciding_only_the_high_findings_no_longer_opens_the_gate(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    """The hole ADR-035 closes: a review finding left undecided used to finalize."""
    run_id = completed_run["id"]
    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    assert any(f["severity"] == "review" for f in findings), "the fixture should raise one"

    for finding in findings:
        if finding["severity"] == "high":
            client.patch(
                f"{api}/findings/{finding['id']}",
                json={"review_status": "false_positive", "review_note": "checked"},
            )

    detail = client.get(f"{api}/runs/{run_id}").json()
    assert detail["can_finalize"] is False
    assert "decision" in detail["finalize_blocked_by"]
    assert client.post(f"{api}/runs/{run_id}/finalize").status_code == 409


def test_low_severity_findings_can_be_decided_in_bulk(
    submit: Submit,
    worker: Worker,
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
) -> None:
    """Bulk OK records OK. Before Phase 6.11a it wrote the Not OK value."""
    run_id = submit("score_value_mismatch").json()["run_id"]
    _run_to_completion(worker)
    _add_low_finding(factory, run_id)

    decided = client.post(f"{api}/runs/{run_id}/findings/bulk-ok").json()
    low = [f for f in client.get(f"{api}/runs/{run_id}/findings").json() if f["severity"] == "low"]

    assert decided == 1
    assert [f["review_status"] for f in low] == ["false_positive"]


def test_bulk_ok_then_finalize_gives_an_ok_verdict(
    submit: Submit,
    worker: Worker,
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
) -> None:
    """The defect Phase 6.11 opened with: "Mark all low OK" must never fail the run.

    Until 6.11a the bulk action stored ``confirmed``, which reads as Not OK on the
    screen and turns the verdict, so one click on a clean run failed the delivery.
    """
    run_id = submit("score_value_mismatch").json()["run_id"]
    _run_to_completion(worker)
    _add_low_finding(factory, run_id)

    client.post(f"{api}/runs/{run_id}/findings/bulk-ok")
    _clear_the_gate(client, api, run_id)

    body = client.post(f"{api}/runs/{run_id}/finalize").json()

    assert body["verdict"] == "ok"
    statuses = {f["review_status"] for f in client.get(f"{api}/runs/{run_id}/findings").json()}
    assert statuses == {"false_positive"}


def test_not_ok_on_a_high_finding_needs_a_comment(
    completed_run: dict[str, Any], client: TestClient, api: str
) -> None:
    """A serious finding marked Not OK has to say what is wrong (Phase 6.11a)."""
    run_id = completed_run["id"]
    high = next(
        f for f in client.get(f"{api}/runs/{run_id}/findings").json() if f["severity"] == "high"
    )

    refused = client.patch(f"{api}/findings/{high['id']}", json={"review_status": "confirmed"})
    assert refused.status_code == 422
    assert "comment" in refused.json()["detail"]

    accepted = client.patch(
        f"{api}/findings/{high['id']}",
        json={"review_status": "confirmed", "review_note": "threshold is wrong"},
    )
    assert accepted.status_code == 200


def test_accepting_a_risk_always_needs_a_comment(
    submit: Submit,
    worker: Worker,
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
) -> None:
    """Accepted risk is the one decision whose reason is the whole record."""
    run_id = submit("score_value_mismatch").json()["run_id"]
    _run_to_completion(worker)
    low_id = _add_low_finding(factory, run_id)

    refused = client.patch(f"{api}/findings/{low_id}", json={"review_status": "accepted_risk"})
    assert refused.status_code == 422

    with_reason = client.patch(
        f"{api}/findings/{low_id}",
        json={"review_status": "accepted_risk", "review_note": "known, signed off last quarter"},
    )
    assert with_reason.status_code == 200


def test_a_low_finding_needs_no_comment_either_way(
    submit: Submit,
    worker: Worker,
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
) -> None:
    """The comment rule is for serious and uncertain findings, not for every click."""
    run_id = submit("score_value_mismatch").json()["run_id"]
    _run_to_completion(worker)
    low_id = _add_low_finding(factory, run_id)

    assert (
        client.patch(f"{api}/findings/{low_id}", json={"review_status": "confirmed"}).status_code
        == 200
    )
    assert (
        client.patch(
            f"{api}/findings/{low_id}", json={"review_status": "false_positive"}
        ).status_code
        == 200
    )


def test_a_decision_survives_a_recheck(
    completed_run: dict[str, Any], worker: Worker, client: TestClient, api: str
) -> None:
    """A re-check must not silently discard a reviewer's work."""
    run_id = completed_run["id"]
    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    target = next(f for f in findings if f["severity"] == "high")
    client.patch(
        f"{api}/findings/{target['id']}",
        json={"review_status": "accepted_risk", "review_note": "known and accepted"},
    )

    client.post(f"{api}/runs/{run_id}/recheck")
    _run_to_completion(worker)

    after = client.get(f"{api}/runs/{run_id}/findings").json()
    same = next(f for f in after if f["title"] == target["title"])
    assert same["review_status"] == "accepted_risk"
    assert same["review_note"] == "known and accepted"


def test_reviewing_an_unknown_finding_is_a_404(client: TestClient, api: str) -> None:
    response = client.patch(f"{api}/findings/9999", json={"review_status": "confirmed"})
    assert response.status_code == 404


# --- criterion 4: a killed worker resumes ---------------------------------------------


def test_a_killed_worker_leaves_a_claimable_job(
    submit: Submit, factory: sessionmaker[Session]
) -> None:
    run_id = submit().json()["run_id"]
    with factory() as session:
        queue = JobQueue(session, is_sqlite=True)
        claimed = queue.claim()
        session.commit()
    assert claimed is not None

    # The worker dies here: the row stays 'running' and nothing finishes it.
    with factory() as session:
        queue = JobQueue(session, is_sqlite=True)
        assert queue.claim() is None
        assert queue.reclaim_stale(older_than_seconds=0) == 1
        session.commit()

    with factory() as session:
        again = JobQueue(session, is_sqlite=True).claim()
        session.commit()
    assert again is not None
    assert again.run_id == run_id
    assert again.attempts == 2


def test_a_resumed_run_skips_the_stages_already_done(
    submit: Submit, worker: Worker, factory: sessionmaker[Session], client: TestClient, api: str
) -> None:
    run_id = submit("baseline_match").json()["run_id"]
    _run_to_completion(worker)
    before = client.get(f"{api}/runs/{run_id}/stats").json()["llm_calls"]

    with factory() as session:
        JobQueue(session, is_sqlite=True).enqueue("run_pipeline", run_id=run_id)
        session.commit()
    _run_to_completion(worker)

    after = client.get(f"{api}/runs/{run_id}/stats").json()["llm_calls"]
    assert after == before, "a resumed run must not redo stages already completed"
