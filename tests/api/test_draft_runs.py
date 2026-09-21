"""A draft you can finish (Phase 6.23c).

Cloning a run already created `Run(status="draft")` prefilled with the submitter's
fields. Nothing could then advance it: no endpoint attached files to an existing run,
edited one's fields, or started it, and `POST /runs` always built a new row. The draft
sat in the list — unreachable, uncancellable — until the purge took it ninety days
later, and the single test covering clone asserted exactly that stranded state.

These tests are the flow that was impossible: clone, edit, replace a file, submit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import sqlalchemy as sa
import starlette.datastructures as datastructures
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models

Submit = Callable[..., Any]


def _clone(client: TestClient, api: str, run_id: int) -> dict[str, Any]:
    body = client.post(f"{api}/runs/{run_id}/clone").json()
    assert body["status"] == "draft"
    return body


def _report_upload(fixtures_root: Path, cases: dict[str, Any], kind: str = "dirt") -> Any:
    case = cases["baseline_match"]
    path = fixtures_root / case["reports"][kind]
    return (
        kind,
        (
            path.name,
            path.read_bytes(),
            "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet",
        ),
    )


# --- what a clone carries -------------------------------------------------------------


def test_a_clone_carries_every_field_the_submitter_typed(
    client: TestClient, api: str, submit: Submit
) -> None:
    """Three of them were dropped, so a cloned run lost its deliverable counts."""
    source = submit(deliverable_count="4", outputs_validated="2", delivery_notes="two segments")
    source_id = source.json()["run_id"]

    draft_id = _clone(client, api, source_id)["run_id"]
    draft = client.get(f"{api}/runs/{draft_id}").json()
    original = client.get(f"{api}/runs/{source_id}").json()

    for field in ("customer_name", "order_number", "configuration_id", "scope", "credit_date"):
        assert draft[field] == original[field]
    assert draft["cloned_from"] == source_id
    assert draft["files"] == {}


def test_cloning_twice_returns_the_draft_you_already_have(
    client: TestClient, api: str, submit: Submit
) -> None:
    """Three clicks used to leave three orphans, each living out the retention window."""
    run_id = submit().json()["run_id"]
    first = _clone(client, api, run_id)["run_id"]
    second = _clone(client, api, run_id)["run_id"]
    third = _clone(client, api, run_id)["run_id"]
    assert first == second == third


def test_a_draft_expires_sooner_than_a_run(client: TestClient, api: str, submit: Submit) -> None:
    """Unsubmitted work is not worth the full retention period."""
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    run = client.get(f"{api}/runs/{run_id}").json()
    draft = client.get(f"{api}/runs/{draft_id}").json()
    assert draft["expires_at"] < run["expires_at"]


# --- editing a draft ------------------------------------------------------------------


def test_a_draft_field_can_be_changed(client: TestClient, api: str, submit: Submit) -> None:
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    response = client.patch(f"{api}/runs/{draft_id}", json={"configuration_id": "CFG-CORRECTED-99"})
    assert response.status_code == 200
    assert response.json()["configuration_id"] == "CFG-CORRECTED-99"


def test_only_the_keys_sent_are_touched(client: TestClient, api: str, submit: Submit) -> None:
    """Partial by ``exclude_unset``, so "unstated" stays expressible.

    A falsy check would make ``0`` mean *do not change* — and ``0`` is exactly how the
    form says the submitter did not give a deliverable count.
    """
    run_id = submit(deliverable_count="4").json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    client.patch(f"{api}/runs/{draft_id}", json={"notes": ""})
    after = client.get(f"{api}/runs/{draft_id}").json()
    assert after["notes"] == ""
    assert after["order_number"], "an absent key must not clear a field"

    client.patch(f"{api}/runs/{draft_id}", json={"deliverable_count": 0})
    assert client.get(f"{api}/runs/{draft_id}").json()["order_number"]


def test_a_bad_credit_date_is_refused(client: TestClient, api: str, submit: Submit) -> None:
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]
    response = client.patch(f"{api}/runs/{draft_id}", json={"credit_date": "not-a-date"})
    assert response.status_code == 422


def test_a_run_that_is_not_a_draft_cannot_be_edited(
    client: TestClient, api: str, submit: Submit
) -> None:
    """The guard that stops this becoming a way to rewrite a finished run."""
    run_id = submit().json()["run_id"]
    response = client.patch(f"{api}/runs/{run_id}", json={"notes": "nope"})
    assert response.status_code == 409
    assert "not a draft" in response.json()["detail"]


# --- files ----------------------------------------------------------------------------


def test_files_can_be_attached_to_a_draft(
    client: TestClient, api: str, submit: Submit, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    response = client.post(
        f"{api}/runs/{draft_id}/files",
        files=[_report_upload(fixtures_root, cases, "dirt")],
    )
    assert response.status_code == 200
    assert "dirt" in response.json()["files"]


def test_replacing_a_kind_removes_the_bytes_it_replaced(
    client: TestClient,
    api: str,
    submit: Submit,
    fixtures_root: Path,
    cases: dict[str, Any],
    factory: sessionmaker[Session],
) -> None:
    """A replaced file must not be left on the volume for the life of the run."""
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    client.post(f"{api}/runs/{draft_id}/files", files=[_report_upload(fixtures_root, cases)])
    client.post(f"{api}/runs/{draft_id}/files", files=[_report_upload(fixtures_root, cases)])

    with factory() as session:
        dirts = [f for f in session.get(models.Run, draft_id).files if f.kind == "dirt"]
    assert len(dirts) == 1, "replacing a kind must not accumulate parts"


def test_files_cannot_be_attached_to_a_submitted_run(
    client: TestClient, api: str, submit: Submit, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    run_id = submit().json()["run_id"]
    response = client.post(
        f"{api}/runs/{run_id}/files", files=[_report_upload(fixtures_root, cases)]
    )
    assert response.status_code == 409


# --- submitting -----------------------------------------------------------------------


def test_a_draft_without_its_artifacts_cannot_be_submitted(
    client: TestClient, api: str, submit: Submit
) -> None:
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]
    response = client.post(f"{api}/runs/{draft_id}/submit", json={})
    assert response.status_code == 400


def test_the_whole_flow_clone_edit_replace_submit(
    client: TestClient,
    api: str,
    submit: Submit,
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """The flow this phase exists for, which no endpoint could express before.

    Clone a run, correct a field, upload the artifacts, and start it.
    """
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    client.patch(f"{api}/runs/{draft_id}", json={"configuration_id": "CFG-FIXED-01"})

    case = cases["baseline_match"]
    uploads = [
        (
            "osl",
            ("osl.docx", (fixtures_root / case["osl"]).read_bytes(), "application/octet-stream"),
        ),
        (
            "config",
            ("config.json", (fixtures_root / case["config"]).read_bytes(), "application/json"),
        ),
    ]
    for kind in case["reports"]:
        uploads.append(_report_upload(fixtures_root, cases, kind))
    assert client.post(f"{api}/runs/{draft_id}/files", files=uploads).status_code == 200

    response = client.post(
        f"{api}/runs/{draft_id}/submit", json={"rerun_reason": "corrected configuration"}
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["duplicate"] is None
    assert body["status"] in ("queued", "held")
    assert body["run_id"] == draft_id, "submitting must start the draft, not make a new run"


def test_submitting_restarts_the_retention_clock(
    client: TestClient,
    api: str,
    submit: Submit,
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """A draft sat on for days still gets its full retention once it is real work."""
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]
    before = client.get(f"{api}/runs/{draft_id}").json()["expires_at"]

    case = cases["baseline_match"]
    uploads = [
        (
            "osl",
            ("osl.docx", (fixtures_root / case["osl"]).read_bytes(), "application/octet-stream"),
        ),
        (
            "config",
            ("config.json", (fixtures_root / case["config"]).read_bytes(), "application/json"),
        ),
    ]
    for kind in case["reports"]:
        uploads.append(_report_upload(fixtures_root, cases, kind))
    client.post(f"{api}/runs/{draft_id}/files", files=uploads)
    client.post(f"{api}/runs/{draft_id}/submit", json={"rerun_reason": "restarting the clock"})

    assert client.get(f"{api}/runs/{draft_id}").json()["expires_at"] > before


# --- discarding -----------------------------------------------------------------------


def test_a_draft_can_be_discarded(
    client: TestClient, api: str, submit: Submit, factory: sessionmaker[Session]
) -> None:
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    assert client.delete(f"{api}/runs/{draft_id}?confirm=delete").status_code == 204
    with factory() as session:
        assert session.get(models.Run, draft_id) is None


def test_discarding_needs_the_typed_word(client: TestClient, api: str, submit: Submit) -> None:
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]
    assert client.delete(f"{api}/runs/{draft_id}").status_code == 400


def test_a_finished_run_cannot_be_deleted(client: TestClient, api: str, submit: Submit) -> None:
    """The guard that keeps this from becoming a delete-run endpoint."""
    run_id = submit().json()["run_id"]
    assert client.delete(f"{api}/runs/{run_id}?confirm=delete").status_code == 409


def test_discarding_is_recorded(
    client: TestClient, api: str, submit: Submit, factory: sessionmaker[Session]
) -> None:
    """Deleted rather than tombstoned, so the audit line is the whole record."""
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]
    client.delete(f"{api}/runs/{draft_id}?confirm=delete")

    with factory() as session:
        actions = set(
            session.execute(
                sa.select(models.AuditLog.action).where(models.AuditLog.run_id == draft_id)
            ).scalars()
        )
    assert "run.draft_discarded" in actions


# --- drafts stay out of the history ---------------------------------------------------


def test_the_runs_list_leaves_drafts_out(client: TestClient, api: str, submit: Submit) -> None:
    """A draft is unfinished work, not a delivery that was validated.

    Letting abandoned ones accumulate in the history puts noise in front of the runs
    somebody is actually looking for, so they are reached by their own filter instead.
    """
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    listed = {row["id"] for row in client.get(f"{api}/runs").json()}
    assert run_id in listed
    assert draft_id not in listed


def test_drafts_are_listed_when_they_are_asked_for(
    client: TestClient, api: str, submit: Submit
) -> None:
    """The filter has to be able to find them, or they would be unreachable."""
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]

    listed = {row["id"] for row in client.get(f"{api}/runs?status=draft").json()}
    assert listed == {draft_id}


def test_asking_for_another_status_still_excludes_drafts(
    client: TestClient, api: str, submit: Submit
) -> None:
    run_id = submit().json()["run_id"]
    _clone(client, api, run_id)

    rows = client.get(f"{api}/runs?status=queued").json()
    assert rows and all(row["status"] == "queued" for row in rows)


# --- the form is closed whatever the answer is ----------------------------------------


def _closes_counted(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count `FormData.close()` calls, which is what releases the spooled files."""
    closed: list[int] = []
    original = datastructures.FormData.close

    async def spy(self: Any) -> None:
        closed.append(id(self))
        await original(self)

    monkeypatch.setattr(datastructures.FormData, "close", spy)
    return closed


def test_a_rejected_draft_upload_still_closes_its_form(
    client: TestClient, api: str, submit: Submit, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal must release the spooled files, because refusals are the common case.

    Every artifact in a multipart form is a `SpooledTemporaryFile` that reading the form
    does not close. `POST /runs/{id}/files` reads every artifact off the raw form, so
    only this endpoint can close them — and it used to do so after the last thing that
    could refuse, which meant a wrong extension, an oversized file or an unknown slot
    each stranded a descriptor and a temporary file for the life of the process.
    """
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]
    closed = _closes_counted(monkeypatch)

    refused = client.post(
        f"{api}/runs/{draft_id}/files",
        files={"dirt": ("dirt.txt", b"not a workbook", "text/plain")},
    )
    assert refused.status_code == 400
    assert closed, "a refused upload left its form open"


def test_a_draft_upload_with_no_known_slot_still_closes_its_form(
    client: TestClient, api: str, submit: Submit, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other refusal on this endpoint, which returns before anything is stored."""
    run_id = submit().json()["run_id"]
    draft_id = _clone(client, api, run_id)["run_id"]
    closed = _closes_counted(monkeypatch)

    refused = client.post(
        f"{api}/runs/{draft_id}/files",
        files={"not_a_slot": ("x.xlsx", b"x" * 32, "application/vnd.ms-excel")},
    )
    assert refused.status_code == 400
    assert closed, "an upload naming no known slot left its form open"


def test_a_refused_submission_still_closes_its_form(
    client: TestClient, api: str, submit: Submit, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    """`POST /runs` refuses on its own account too, and every refusal is a form to close.

    It declares its OSL and config as parameters, so the framework happens to close the
    form for it today. That is an accident of how the framework reads a body, not a
    property of this endpoint, and the refusal path is asserted here so an upgrade or a
    signature change cannot quietly turn it back into a leak.
    """
    closed: list[int] = []
    original = datastructures.FormData.close

    async def spy(self: Any) -> None:
        closed.append(id(self))
        await original(self)

    case = cases["baseline_match"]
    osl = fixtures_root / case["osl"]
    config = fixtures_root / case["config"]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(datastructures.FormData, "close", spy)
        refused = client.post(
            f"{api}/runs",
            data={
                "customer_name": "Acme",
                "order_number": "ORD-FORM",
                "configuration_id": "CFG-FORM",
            },
            files=[
                ("osl", (osl.name, osl.read_bytes(), "application/octet-stream")),
                ("config", (config.name, config.read_bytes(), "application/json")),
                ("dirt", ("dirt.txt", b"not a workbook", "text/plain")),
            ],
        )
    assert refused.status_code == 400
    assert closed, "a refused submission left its form open"
