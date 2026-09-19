"""Tests for the run endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models

Submit = Callable[..., Any]


def test_health_reports_the_backend(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


# --- creating a run -------------------------------------------------------------------


def test_a_submission_creates_a_queued_run(submit: Submit) -> None:
    response = submit()
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["queue_position"] == 1
    assert body["duplicate"] is None


def test_the_uploaded_files_are_recorded(submit: Submit, factory: sessionmaker[Session]) -> None:
    run_id = submit().json()["run_id"]
    with factory() as session:
        kinds = {f.kind for f in session.get(models.Run, run_id).files}
    assert {"osl", "config", "dirt", "counts"} <= kinds


def test_the_files_land_on_the_shared_volume(
    submit: Submit, factory: sessionmaker[Session], db_settings: Any
) -> None:
    run_id = submit().json()["run_id"]
    with factory() as session:
        for file in session.get(models.Run, run_id).files:
            assert (db_settings.data_dir / file.storage_key).exists()


def test_a_job_is_queued_for_the_run(submit: Submit, factory: sessionmaker[Session]) -> None:
    run_id = submit().json()["run_id"]
    with factory() as session:
        job = session.execute(sa.select(models.Job).where(models.Job.run_id == run_id)).scalar_one()
    assert job.task == "run_pipeline"
    assert job.status == "queued"


def test_the_config_is_captured_and_versioned(
    submit: Submit, factory: sessionmaker[Session]
) -> None:
    submit()
    with factory() as session:
        configs = list(session.execute(sa.select(models.Config)).scalars())
    assert len(configs) == 1
    assert configs[0].version == 1
    assert configs[0].content["configuration_id"]


def test_an_unchanged_config_is_not_versioned_twice(
    submit: Submit, factory: sessionmaker[Session]
) -> None:
    submit()
    submit(rerun_reason="checking the version logic")
    with factory() as session:
        versions = list(session.execute(sa.select(models.Config.version)).scalars())
    assert versions == [1]


def test_a_run_without_reports_is_rejected(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    case = cases["baseline_match"]
    response = client.post(
        f"{api}/runs",
        data={
            "customer_name": "X",
            "order_number": "O-1",
            "configuration_id": "C-1",
        },
        files=[
            (
                "osl",
                (
                    "osl.docx",
                    (fixtures_root / case["osl"]).read_bytes(),
                    "application/octet-stream",
                ),
            ),
            ("config", ("config.json", b"{}", "application/json")),
        ],
    )
    assert response.status_code == 400
    assert "report" in response.json()["detail"]


def test_a_disallowed_file_type_is_rejected(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    case = cases["baseline_match"]
    response = client.post(
        f"{api}/runs",
        data={"customer_name": "X", "order_number": "O-1", "configuration_id": "C-1"},
        files=[
            (
                "osl",
                (
                    "osl.docx",
                    (fixtures_root / case["osl"]).read_bytes(),
                    "application/octet-stream",
                ),
            ),
            ("config", ("config.json", b"{}", "application/json")),
            ("dirt", ("evil.exe", b"MZ", "application/octet-stream")),
        ],
    )
    assert response.status_code == 400
    assert ".exe" in response.json()["detail"]


def test_too_many_queued_runs_for_one_order_is_refused(submit: Submit) -> None:
    """Repeated submissions are a retry, not a request for parallel work."""
    submit()
    submit(rerun_reason="second")
    submit(rerun_reason="third")
    response = submit(rerun_reason="fourth")
    assert response.status_code == 409
    assert "already queued" in response.json()["detail"]


# --- duplicate detection ----------------------------------------------------------------


def test_identical_inputs_return_the_existing_run(submit: Submit) -> None:
    first = submit().json()
    second = submit().json()
    assert second["run_id"] is None
    assert second["duplicate"]["run_id"] == first["run_id"]
    assert "already run" in second["duplicate"]["message"]


def test_a_rerun_reason_creates_a_new_run(submit: Submit) -> None:
    first = submit().json()
    second = submit(rerun_reason="the prompt version changed").json()
    assert second["run_id"] != first["run_id"]
    assert second["duplicate"] is None


def test_the_rerun_reason_is_stored_and_audited(
    submit: Submit, factory: sessionmaker[Session]
) -> None:
    submit()
    run_id = submit(rerun_reason="a check was added").json()["run_id"]
    with factory() as session:
        assert session.get(models.Run, run_id).rerun_reason == "a check was added"
        actions = list(session.execute(sa.select(models.AuditLog.action)).scalars())
    assert actions.count("run.created") == 2


def test_a_blocked_duplicate_is_audited(submit: Submit, factory: sessionmaker[Session]) -> None:
    submit()
    submit()
    with factory() as session:
        actions = list(session.execute(sa.select(models.AuditLog.action)).scalars())
    assert "run.duplicate_blocked" in actions


def test_an_active_check_change_invalidates_the_duplicate_shortcut(
    submit: Submit, factory: sessionmaker[Session]
) -> None:
    """The same files deserve a fresh run once the rules applied to them changed."""
    first = submit().json()
    with factory() as session:
        session.add(
            models.CheckDefinitionRow(name="new_check", expression="1 == 1", is_active=True)
        )
        session.commit()
    second = submit().json()
    assert second["run_id"] is not None
    assert second["run_id"] != first["run_id"]


def test_a_failed_run_does_not_block_a_resubmission(
    submit: Submit, factory: sessionmaker[Session]
) -> None:
    run_id = submit().json()["run_id"]
    with factory() as session:
        session.get(models.Run, run_id).status = "failed"
        session.commit()
    assert submit().json()["run_id"] is not None


# --- reading runs ---------------------------------------------------------------------------


def test_runs_are_listed_newest_first(submit: Submit, client: TestClient, api: str) -> None:
    submit()
    submit(rerun_reason="second")
    body = client.get(f"{api}/runs").json()
    assert len(body) == 2
    assert body[0]["id"] > body[1]["id"]


def test_runs_can_be_filtered_by_status(submit: Submit, client: TestClient, api: str) -> None:
    submit()
    assert len(client.get(f"{api}/runs", params={"status": "queued"}).json()) == 1
    assert client.get(f"{api}/runs", params={"status": "finalized"}).json() == []


def test_a_run_reports_its_queue_position(submit: Submit, client: TestClient, api: str) -> None:
    run_id = submit().json()["run_id"]
    assert client.get(f"{api}/runs/{run_id}").json()["queue_position"] == 1


def test_an_unknown_run_is_a_404(client: TestClient, api: str) -> None:
    assert client.get(f"{api}/runs/9999").status_code == 404


def test_run_detail_carries_the_fields_the_review_screen_needs(
    submit: Submit, client: TestClient, api: str
) -> None:
    run_id = submit().json()["run_id"]
    body = client.get(f"{api}/runs/{run_id}").json()
    assert set(body) >= {
        "id",
        "customer_name",
        "status",
        "stages",
        "files",
        "can_finalize",
        "finalized",
        "high",
        "medium",
        "low",
    }


def test_clone_prefills_a_draft_run(submit: Submit, client: TestClient, api: str) -> None:
    """A clone is usually a re-run with corrected inputs, so its files are not copied."""
    run_id = submit().json()["run_id"]
    body = client.post(f"{api}/runs/{run_id}/clone").json()
    assert body["cloned_from"] == run_id
    assert body["status"] == "draft"
    clone = client.get(f"{api}/runs/{body['run_id']}").json()
    assert clone["customer_name"] == client.get(f"{api}/runs/{run_id}").json()["customer_name"]
    assert clone["files"] == {}
