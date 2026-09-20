"""Tests for admin-configurable artifact types and run scopes over HTTP (ADR-020).

What these pin down: the new-run form is generated from the catalog, switching a type
off removes its upload slot, built-ins can be disabled but never deleted, and a type a
run has already used survives so the history stays readable.
"""

from __future__ import annotations

from typing import Any, Callable

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models

Submit = Callable[..., Any]


def _save(client: TestClient, api: str, **fields: Any) -> Any:
    """Post an artifact type with the required fields filled in."""
    body = {"key": "x", "label": "X", **fields}
    return client.post(f"{api}/admin/artifact-types", json=body)


# --- the catalog over HTTP ----------------------------------------------------------


def test_listing_seeds_the_defaults_into_an_empty_database(client: TestClient, api: str) -> None:
    """A fresh install is configurable rather than blank."""
    response = client.get(f"{api}/admin/artifact-types")
    assert response.status_code == 200, response.text
    rows = response.json()
    keys = [row["key"] for row in rows]
    assert keys[:2] == ["osl", "config"]
    assert "dirt" in keys
    assert all(row["is_builtin"] for row in rows)
    assert next(r for r in rows if r["key"] == "score_distribution")["is_active"] is False


def test_an_administrator_can_define_a_new_report_type(client: TestClient, api: str) -> None:
    """Defining a report and its meaning needs no code change."""
    response = _save(
        client,
        api,
        key="Tradeline_Mix",
        label="Tradeline mix",
        description="Counts by tradeline category.",
        ai_context="Revolving and installment must both appear.",
        sort_order=95,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["key"] == "tradeline_mix"
    assert body["is_builtin"] is False
    assert body["ai_context"] == "Revolving and installment must both appear."


def test_a_malformed_key_is_rejected(client: TestClient, api: str) -> None:
    """Keys become multipart field names, so they have to be well behaved."""
    assert _save(client, api, key="Field Distribution!").status_code == 422


def test_a_builtin_cannot_change_kind_or_be_deleted(client: TestClient, api: str) -> None:
    """The fixed report checks look a built-in up by key, so it must stay put."""
    client.get(f"{api}/admin/artifact-types")
    changed = _save(client, api, key="dirt", label="DIRT", kind="config")
    assert changed.status_code == 422
    assert "built-in" in changed.json()["detail"]

    deleted = client.delete(f"{api}/admin/artifact-types/dirt")
    assert deleted.status_code == 409
    assert "switch it off" in deleted.json()["detail"]


def test_an_unused_admin_defined_type_can_be_deleted(client: TestClient, api: str) -> None:
    """Nothing refers to it, so removing it loses no history."""
    assert _save(client, api, key="scratch", label="Scratch").status_code == 201
    assert client.delete(f"{api}/admin/artifact-types/scratch").status_code == 204
    assert client.delete(f"{api}/admin/artifact-types/scratch").status_code == 404


def test_a_type_a_run_has_used_cannot_be_deleted(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """Deleting it would leave a stored run referring to a type nothing describes."""
    assert _save(client, api, key="scratch", label="Scratch").status_code == 201
    assert submit().status_code == 201
    with factory() as session:
        run_id = session.execute(sa.select(models.Run.id)).scalars().first()
        session.add(
            models.RunFile(
                run_id=run_id,
                kind="scratch",
                filename="s.xlsx",
                storage_key="runs/1/scratch.xlsx",
                sha256="0" * 64,
            )
        )
        session.commit()

    response = client.delete(f"{api}/admin/artifact-types/scratch")
    assert response.status_code == 409
    assert "switch it off" in response.json()["detail"]


def test_a_sample_upload_is_recorded_against_the_type(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """Uploading a sample is how an administrator shows what the report looks like."""
    path = fixtures_root / cases["baseline_match"]["reports"]["dirt"]
    response = client.post(
        f"{api}/admin/artifact-types/dirt/samples",
        files={
            "file": (
                "dirt_sample.xlsx",
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["samples"]) == 1
    assert body["samples"][0]["filename"] == "dirt_sample.xlsx"
    assert body["sheets"]

    assert (
        client.post(
            f"{api}/admin/artifact-types/nope/samples",
            files={
                "file": (
                    "s.xlsx",
                    b"x",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        ).status_code
        == 404
    )


# --- scopes -------------------------------------------------------------------------


def test_the_shipped_scopes_are_the_three_programmes_plus_a_catch_all(
    client: TestClient, api: str
) -> None:
    """Most customers fall into AM, AS, or Archives; the rest are clubbed together."""
    rows = client.get(f"{api}/admin/scopes").json()
    assert [row["code"] for row in rows] == ["AM", "AS", "ARCHIVE", "OTHER"]
    assert all(row["standing_instructions"] == "" for row in rows)


def test_standing_instructions_can_be_written_once_per_programme(
    client: TestClient, api: str
) -> None:
    """The compliance regime the OSL does not restate belongs here."""
    response = client.post(
        f"{api}/admin/scopes",
        json={
            "code": "am",
            "label": "Account Monitoring",
            "standing_instructions": "Opt-out suppression is mandatory.",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["code"] == "AM"
    assert response.json()["standing_instructions"] == "Opt-out suppression is mandatory."

    assert (
        client.post(f"{api}/admin/scopes", json={"code": "a b", "label": "Bad"}).status_code == 422
    )


def test_a_scope_in_use_cannot_be_deleted(client: TestClient, api: str, submit: Submit) -> None:
    """A stored run naming it must keep reading sensibly."""
    client.get(f"{api}/admin/scopes")
    assert submit(scope="AM").status_code == 201
    response = client.delete(f"{api}/admin/scopes/AM")
    assert response.status_code == 409
    assert client.delete(f"{api}/admin/scopes/ARCHIVE").status_code == 204


# --- the new-run form ---------------------------------------------------------------


def test_the_new_run_form_is_generated_from_the_catalog(client: TestClient, api: str) -> None:
    """Switching a type off removes its upload slot without a deploy."""
    before = client.get(f"{api}/runs/options").json()
    assert [s["code"] for s in before["scopes"]] == ["AM", "AS", "ARCHIVE", "OTHER"]
    slots = {a["key"]: a for a in before["artifacts"]}
    assert slots["osl"]["is_required"] is True and slots["osl"]["accept"] == ".docx,.pdf"
    assert slots["config"]["accept"] == ".json"
    assert slots["dirt"]["accept"] == ".xlsx"
    assert "score_distribution" not in slots

    assert (
        _save(
            client, api, key="field_distribution", label="Field distribution", is_active=False
        ).status_code
        == 201
    )

    after = client.get(f"{api}/runs/options").json()
    assert "field_distribution" not in {a["key"] for a in after["artifacts"]}


def test_a_disabled_scope_is_not_offered(client: TestClient, api: str) -> None:
    """Switching a programme off stops users seeing it."""
    client.get(f"{api}/admin/scopes")
    assert (
        client.post(
            f"{api}/admin/scopes", json={"code": "ARCHIVE", "label": "Archives", "is_active": False}
        ).status_code
        == 201
    )
    codes = {s["code"] for s in client.get(f"{api}/runs/options").json()["scopes"]}
    assert "ARCHIVE" not in codes


# --- scope and suppressions on a run ------------------------------------------------


def test_a_run_records_its_programme_and_suppression_answer(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """Both add context for the model about the kind of validation to do."""
    assert submit(scope="AS", has_suppressions="true").status_code == 201
    with factory() as session:
        run = session.execute(sa.select(models.Run)).scalars().one()
        assert run.scope == "AS"
        assert run.has_suppressions is True


def test_suppressions_default_to_no(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """The form defaults to no, and a form that omits the field means the same."""
    assert submit().status_code == 201
    with factory() as session:
        run = session.execute(sa.select(models.Run)).scalars().one()
        assert run.has_suppressions is False
        assert run.scope == ""


def test_a_report_switched_off_is_still_accepted_when_another_is_uploaded(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """Dropping a slot must not drop every report, which a subclass bug once did."""
    assert submit().status_code == 201
    with factory() as session:
        kinds = set(session.execute(sa.select(models.RunFile.kind)).scalars())
    assert {"osl", "config"} < kinds
    assert kinds - {"osl", "config"}


def test_configured_guidance_reaches_the_prompts(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    submit: Submit,
    worker: Any,
    monkeypatch: Any,
) -> None:
    """The point of the feature: what an administrator writes reaches the model."""
    client.get(f"{api}/admin/artifact-types")
    assert (
        client.post(
            f"{api}/admin/scopes",
            json={
                "code": "AM",
                "label": "Account Monitoring",
                "standing_instructions": "Opt-out suppression is mandatory.",
            },
        ).status_code
        == 201
    )
    assert (
        _save(
            client,
            api,
            key="osl",
            label="OSL — requirement spec",
            kind="osl",
            is_required=True,
            ai_context="Ignore the cover page.",
            sort_order=10,
        ).status_code
        == 201
    )

    seen: list[str] = []
    from greenlight_ai.llm import base as llm_base

    original = llm_base.BaseClient.complete

    def _record(self: Any, system: str, user: str, *args: Any, **kwargs: Any) -> Any:
        seen.append(user)
        return original(self, system, user, *args, **kwargs)

    monkeypatch.setattr(llm_base.BaseClient, "complete", _record)

    assert submit(scope="AM", has_suppressions="true").status_code == 201
    worker.run_once()

    assert seen, "the pipeline made no model call"
    joined = "\n".join(seen)
    assert "This delivery is Account Monitoring." in joined
    assert "Suppressions were applied to it." in joined
    assert "Opt-out suppression is mandatory." in joined
    assert "About the document below: Ignore the cover page." in joined


# --- samples (ADR-021) --------------------------------------------------------------


def _sample(
    fixtures_root: Any, cases: dict[str, Any], kind: str = "dirt"
) -> tuple[str, bytes, str]:
    """A synthetic workbook to upload as a sample."""
    path = fixtures_root / cases["baseline_match"]["reports"][kind]
    return (
        f"{kind}_sample.xlsx",
        path.read_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def test_a_type_holds_up_to_three_samples(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """Real layouts vary between customers, and one sample hides that."""
    for index in range(3):
        response = client.post(
            f"{api}/admin/artifact-types/dirt/samples",
            files={"file": _sample(fixtures_root, cases)},
            data={"label": f"customer {index}"},
        )
        assert response.status_code == 201, response.text

    body = response.json()
    assert len(body["samples"]) == 3
    assert [s["label"] for s in body["samples"]] == ["customer 0", "customer 1", "customer 2"]

    fourth = client.post(
        f"{api}/admin/artifact-types/dirt/samples",
        files={"file": _sample(fixtures_root, cases)},
    )
    assert fourth.status_code == 409
    assert "remove one" in fourth.json()["detail"]


def test_a_sample_can_be_downloaded_and_removed(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """An administrator has to be able to open the sample in use, not just read about it."""
    name, content, media = _sample(fixtures_root, cases)
    created = client.post(
        f"{api}/admin/artifact-types/dirt/samples", files={"file": (name, content, media)}
    ).json()
    sample_id = created["samples"][0]["id"]

    downloaded = client.get(f"{api}/admin/artifact-types/dirt/samples/{sample_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert name in downloaded.headers["content-disposition"]

    assert client.delete(f"{api}/admin/artifact-types/dirt/samples/{sample_id}").status_code == 204
    after = client.get(f"{api}/admin/artifact-types").json()
    assert next(t for t in after if t["key"] == "dirt")["samples"] == []


def test_a_sample_preview_shows_cells_with_their_labels(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """This is what someone reads while deciding where a named value should point."""
    created = client.post(
        f"{api}/admin/artifact-types/counts/samples",
        files={"file": _sample(fixtures_root, cases, "counts")},
    ).json()
    sample_id = created["samples"][0]["id"]

    preview = client.get(f"{api}/admin/artifact-types/counts/samples/{sample_id}/preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["sheets"]
    first = body["sheets"][0]
    assert first["name"]
    assert first["cells"]
    assert all(cell["cell"] for cell in first["cells"])


def test_a_sample_of_another_type_is_not_reachable_through_this_one(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """The key in the path is part of the identity, not decoration."""
    created = client.post(
        f"{api}/admin/artifact-types/dirt/samples",
        files={"file": _sample(fixtures_root, cases)},
    ).json()
    sample_id = created["samples"][0]["id"]
    assert (
        client.get(f"{api}/admin/artifact-types/counts/samples/{sample_id}/preview").status_code
        == 404
    )


# --- working out what a workbook is (phase 6.1d) -------------------------------------


def _upload_sample(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any], key: str
) -> None:
    """Store a fixture workbook as a sample of one artifact type."""
    response = client.post(
        f"{api}/admin/artifact-types/{key}/samples",
        files={"file": _sample(fixtures_root, cases, key)},
    )
    assert response.status_code == 201, response.text


def _detect(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any], kind: str
) -> Any:
    """Post a fixture workbook to the detector."""
    return client.post(
        f"{api}/runs/detect-type", files={"file": _sample(fixtures_root, cases, kind)}
    )


def test_detection_recognises_a_workbook_of_a_stored_layout(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """A user should not have to know that their file is a "field distribution"."""
    _upload_sample(client, api, fixtures_root, cases, "counts")
    _upload_sample(client, api, fixtures_root, cases, "dirt")

    response = _detect(client, api, fixtures_root, cases, "counts")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "confident"
    assert body["key"] == "counts"
    assert body["reason"]
    assert [c["key"] for c in body["candidates"]][0] == "counts"
    assert [s["key"] for s in body["sheets"]] == ["counts"]


def test_detection_says_it_does_not_know(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """An uncertain guess has to be representable, not rounded up to a best guess."""
    _upload_sample(client, api, fixtures_root, cases, "dirt")

    body = _detect(client, api, fixtures_root, cases, "state_distribution").json()
    assert body["verdict"] == "unknown"
    assert body["key"] is None
    assert body["candidates"] == []


def test_detection_of_a_multi_tab_workbook_maps_each_sheet(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """A field distribution can have multiple tabs, so detection runs per sheet."""
    _upload_sample(client, api, fixtures_root, cases, "dirt")
    _upload_sample(client, api, fixtures_root, cases, "counts")

    body = _detect(client, api, fixtures_root, cases, "dirt").json()
    sheets = body["sheets"]
    assert len(sheets) > 1
    assert {s["sheet"] for s in sheets} == {"Summary", "Attributes", "Sample"}
    assert all(s["key"] == "dirt" for s in sheets)


def test_detection_rejects_something_that_is_not_a_workbook(
    client: TestClient, api: str, fixtures_root: Any, cases: dict[str, Any]
) -> None:
    """The file is read and thrown away; a bad one is a 400, not a stored artefact."""
    _upload_sample(client, api, fixtures_root, cases, "dirt")
    response = client.post(
        f"{api}/runs/detect-type",
        files={"file": ("notes.xlsx", b"this is not a workbook", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "workbook" in response.json()["detail"]


def test_detection_does_not_store_the_uploaded_file(
    client: TestClient,
    api: str,
    db_settings: Any,
    fixtures_root: Any,
    cases: dict[str, Any],
) -> None:
    """An unassigned upload belongs to no run, so no retention rule would remove it."""
    _upload_sample(client, api, fixtures_root, cases, "counts")
    before = {p.name for p in db_settings.data_dir.rglob("*") if p.is_file()}
    assert _detect(client, api, fixtures_root, cases, "counts").status_code == 200
    after = {p.name for p in db_settings.data_dir.rglob("*") if p.is_file()}
    assert after == before
