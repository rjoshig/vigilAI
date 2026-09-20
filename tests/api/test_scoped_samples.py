"""Samples belong to a programme or are global; three per type per programme (6.10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _add(
    client: TestClient, api: str, root: Path, cases: dict[str, Any], scope: str, n: int
) -> Any:
    path = root / cases["baseline_match"]["reports"]["counts"]
    return client.post(
        f"{api}/admin/artifact-types/counts/samples",
        data={"label": f"{scope or 'global'}-{n}", "scope_code": scope},
        files={"file": (f"c{n}.xlsx", path.read_bytes(), XLSX)},
    )


def test_three_per_programme_and_three_global_coexist(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    client.get(f"{api}/admin/artifact-types")
    for n in range(3):
        assert _add(client, api, fixtures_root, cases, "", n).status_code == 201
    assert _add(client, api, fixtures_root, cases, "", 3).status_code == 409
    for n in range(3):
        assert _add(client, api, fixtures_root, cases, "AS", n).status_code == 201
    fourth = _add(client, api, fixtures_root, cases, "as", 3)
    assert fourth.status_code == 409
    assert "programme AS" in fourth.json()["detail"]
    types = {t["key"]: t for t in client.get(f"{api}/admin/artifact-types").json()}
    scopes = sorted(s["scope_code"] for s in types["counts"]["samples"])
    assert scopes == ["", "", "", "AS", "AS", "AS"]


def test_an_unknown_programme_is_refused(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    client.get(f"{api}/admin/artifact-types")
    assert _add(client, api, fixtures_root, cases, "ZZ", 0).status_code == 404


def test_a_sample_can_be_relabelled_annotated_and_moved_between_scopes(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    client.get(f"{api}/admin/artifact-types")
    for n in range(3):
        assert _add(client, api, fixtures_root, cases, "AS", n).status_code == 201
    added = _add(client, api, fixtures_root, cases, "", 0).json()
    sample_id = next(s["id"] for s in added["samples"] if s["scope_code"] == "")

    edited = client.patch(
        f"{api}/admin/artifact-types/counts/samples/{sample_id}",
        json={"label": "Q3", "notes": "the monitoring variant has no billing sheet"},
    )
    assert edited.status_code == 200, edited.text
    sample = next(s for s in edited.json()["samples"] if s["id"] == sample_id)
    assert (sample["label"], sample["notes"]) == (
        "Q3",
        "the monitoring variant has no billing sheet",
    )

    full = client.patch(
        f"{api}/admin/artifact-types/counts/samples/{sample_id}", json={"scope_code": "as"}
    )
    assert full.status_code == 409
    moved = client.patch(
        f"{api}/admin/artifact-types/counts/samples/{sample_id}", json={"scope_code": "AM"}
    )
    assert moved.status_code == 200
    assert next(s for s in moved.json()["samples"] if s["id"] == sample_id)["scope_code"] == "AM"
    unknown = client.patch(
        f"{api}/admin/artifact-types/counts/samples/{sample_id}", json={"scope_code": "ZZ"}
    )
    assert unknown.status_code == 404
