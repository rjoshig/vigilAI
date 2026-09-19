"""Tests for versioned definitions with revert (Phase 6.8c, ADR-029)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models, versions
from greenlight_ai.db.settings import DbSettings

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _save_type(client: TestClient, api: str, **fields: Any) -> Any:
    body = {"key": "counts", "label": "Counts", "description": "d", **fields}
    return client.post(f"{api}/admin/artifact-types", json=body)


def _add_sample(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any], label: str
) -> Any:
    path = fixtures_root / cases["baseline_match"]["reports"]["counts"]
    return client.post(
        f"{api}/admin/artifact-types/counts/samples",
        data={"label": label},
        files={"file": (f"{label}.xlsx", path.read_bytes(), XLSX)},
    )


def _versions(
    client: TestClient, api: str, kind: str = "artifact-type", key: str = "counts"
) -> Any:
    response = client.get(f"{api}/admin/versions/{kind}/{key}")
    assert response.status_code == 200, response.text
    return response.json()


# --- artifact types -------------------------------------------------------------------


def test_every_save_of_an_artifact_type_is_a_version_and_only_ten_are_listed(
    client: TestClient, api: str
) -> None:
    for n in range(1, 13):
        assert _save_type(client, api, description=f"edit {n}").status_code == 201
    listed = _versions(client, api)
    assert len(listed) == versions.KEEP_VERSIONS
    assert [v["version"] for v in listed][:2] == [12, 11]
    assert listed[0]["summary"] == "description changed"
    assert listed[0]["snapshot"]["description"] == "edit 12"


def test_saving_the_same_thing_twice_writes_one_version(client: TestClient, api: str) -> None:
    _save_type(client, api, description="same")
    _save_type(client, api, description="same")
    assert len(_versions(client, api)) == 1


def test_revert_restores_fields_and_samples_and_is_itself_a_new_version(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    _save_type(client, api, description="first")  # v1
    assert _add_sample(client, api, fixtures_root, cases, "one").status_code == 201  # v2
    _save_type(client, api, description="second")  # v3
    stored = client.get(f"{api}/admin/artifact-types").json()
    counts = next(t for t in stored if t["key"] == "counts")
    sample_id = counts["samples"][0]["id"]
    assert (
        client.delete(f"{api}/admin/artifact-types/counts/samples/{sample_id}").status_code == 204
    )  # v4
    assert len(_versions(client, api)) == 4

    refused = client.post(
        f"{api}/admin/versions/artifact-type/counts/2/revert", json={"confirm": "nope"}
    )
    assert refused.status_code == 400

    reverted = client.post(
        f"{api}/admin/versions/artifact-type/counts/2/revert", json={"confirm": "revert"}
    )
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["version"] == 5
    assert reverted.json()["reverted_from"] == 2

    stored = client.get(f"{api}/admin/artifact-types").json()
    counts = next(t for t in stored if t["key"] == "counts")
    assert counts["description"] == "first"
    assert [s["label"] for s in counts["samples"]] == ["one"]


def test_a_missing_version_is_a_404(client: TestClient, api: str) -> None:
    _save_type(client, api)
    response = client.post(
        f"{api}/admin/versions/artifact-type/counts/99/revert", json={"confirm": "revert"}
    )
    assert response.status_code == 404
    assert client.get(f"{api}/admin/versions/nonsense/counts").status_code == 404


def test_a_deleted_samples_workbook_stays_until_no_version_names_it(
    client: TestClient,
    api: str,
    fixtures_root: Path,
    cases: dict[str, Any],
    factory: sessionmaker[Session],
    db_settings: DbSettings,
) -> None:
    _save_type(client, api)
    _add_sample(client, api, fixtures_root, cases, "one")
    stored = client.get(f"{api}/admin/artifact-types").json()
    sample_id = next(t for t in stored if t["key"] == "counts")["samples"][0]["id"]
    with factory() as session:
        sample = session.get(models.ArtifactSample, sample_id)
        assert sample is not None
        path = sample.storage_path
    client.delete(f"{api}/admin/artifact-types/counts/samples/{sample_id}")
    assert (db_settings.data_dir / path).exists()

    with factory() as session:
        # Nothing to prune yet: every version is within the ten.
        assert versions.remove_orphan_samples(session, db_settings.data_dir, "templates") == 0
        session.execute(sa.delete(models.DefinitionVersion))
        session.commit()
        assert versions.remove_orphan_samples(session, db_settings.data_dir, "templates") == 1
    assert not (db_settings.data_dir / path).exists()


def test_a_version_a_run_still_references_survives_pruning(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _save_type(client, api, description="v1")
    with factory() as session:
        run = models.Run(
            customer_name="Acme",
            order_number="O-1",
            configuration_id="C-1",
            definition_versions={"artifact_type:counts": 1},
        )
        session.add(run)
        session.commit()
    for n in range(2, 14):
        _save_type(client, api, description=f"v{n}")
    with factory() as session:
        pruned = versions.prune_versions(session)
        session.commit()
        kept = sorted(
            session.execute(
                sa.select(models.DefinitionVersion.version).where(
                    models.DefinitionVersion.object_key == "counts"
                )
            ).scalars()
        )
    assert pruned == 2
    assert kept == [1] + list(range(4, 14))


# --- programme rules ------------------------------------------------------------------


def _rule(client: TestClient, api: str, **fields: Any) -> Any:
    body = {
        "scope_code": "AS",
        "title": "Opt-outs excluded",
        "text": "Every prescreen delivery excludes opt-outs.",
        "strictness": "must",
        **fields,
    }
    return client.post(f"{api}/admin/programme-rules", json=body)


def test_a_programmes_rule_set_is_versioned_and_reverts_as_a_set(
    client: TestClient, api: str
) -> None:
    client.get(f"{api}/admin/scopes")
    first = _rule(client, api).json()  # v1
    second = _rule(client, api, title="Bands as in the OSL", strictness="should").json()  # v2
    edited = client.patch(
        f"{api}/admin/programme-rules/{first['id']}",
        json={
            "scope_code": "AS",
            "title": first["title"],
            "text": first["text"],
            "strictness": "advisory",
            "sort_order": first["sort_order"],
        },
    )
    assert edited.status_code == 200  # v3
    listed = _versions(client, api, "programme", "AS")
    assert [v["version"] for v in listed] == [3, 2, 1]
    assert listed[0]["summary"].startswith("rule edited")

    reverted = client.post(
        f"{api}/admin/versions/programme/AS/1/revert", json={"confirm": "revert"}
    )
    assert reverted.status_code == 200, reverted.text
    rules = client.get(f"{api}/admin/programme-rules?scope_code=AS").json()
    by_id = {r["id"]: r for r in rules}
    assert by_id[first["id"]]["strictness"] == "must"
    # The rule that did not exist at version 1 is deleted, restorable from the Rules screen.
    assert second["id"] not in by_id
    assert len(_versions(client, api, "programme", "AS")) == 4


def test_two_samples_of_one_type_keep_two_files(
    client: TestClient,
    api: str,
    fixtures_root: Path,
    cases: dict[str, Any],
    db_settings: DbSettings,
) -> None:
    """Regression: samples used to share ``runs/templates/<key>.xlsx`` and overwrite."""
    _save_type(client, api)
    _add_sample(client, api, fixtures_root, cases, "one")
    _add_sample(client, api, fixtures_root, cases, "two")
    with_paths = client.get(f"{api}/admin/artifact-types").json()
    counts = next(t for t in with_paths if t["key"] == "counts")
    assert len(counts["samples"]) == 2
    files = list((db_settings.data_dir / "runs" / "templates").rglob("*.xlsx"))
    assert len(files) == 2
