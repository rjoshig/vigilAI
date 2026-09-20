"""An OSL or a configuration sample previews as its own shape, not as a workbook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.parsers.test_osl_pdf import write_pdf


def _upload(client: TestClient, api: str, key: str, name: str, data: bytes, ctype: str) -> int:
    response = client.post(
        f"{api}/admin/artifact-types/{key}/samples", files={"file": (name, data, ctype)}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["samples"][-1]["id"])


def test_a_docx_osl_sample_previews_as_sections(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    client.get(f"{api}/admin/artifact-types")
    data = (fixtures_root / cases["baseline_match"]["osl"]).read_bytes()
    sample_id = _upload(client, api, "osl", "osl.docx", data, "application/octet-stream")
    preview = client.get(f"{api}/admin/artifact-types/osl/samples/{sample_id}/preview").json()
    names = [sheet["name"] for sheet in preview["sheets"]]
    assert any("Geography" in name for name in names)
    geography = next(sheet for sheet in preview["sheets"] if "Geography" in sheet["name"])
    assert geography["cells"][0]["cell"] == "¶1"
    assert "Illinois" in geography["cells"][0]["value"]


def test_a_pdf_osl_sample_is_accepted_and_previews(
    client: TestClient, api: str, tmp_path: Path
) -> None:
    client.get(f"{api}/admin/artifact-types")
    path = tmp_path / "osl.pdf"
    write_pdf(path, ["OSL", "2 Population", "The input population is 250,000 records."])
    sample_id = _upload(client, api, "osl", "osl.pdf", path.read_bytes(), "application/pdf")
    preview = client.get(f"{api}/admin/artifact-types/osl/samples/{sample_id}/preview").json()
    assert preview["sheets"][0]["name"] == "2 Population"


def test_a_config_sample_previews_as_blocks_by_path(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    client.get(f"{api}/admin/artifact-types")
    data = (fixtures_root / cases["baseline_match"]["config"]).read_bytes()
    sample_id = _upload(client, api, "config", "config.json", data, "application/json")
    preview = client.get(f"{api}/admin/artifact-types/config/samples/{sample_id}/preview").json()
    cells = {cell["cell"]: cell for cell in preview["sheets"][0]["cells"]}
    assert "rules.score_v3" in cells
    assert cells["rules.score_v3"]["label"] == "rules"


def test_artifact_types_and_programmes_carry_their_version(client: TestClient, api: str) -> None:
    client.get(f"{api}/admin/artifact-types")
    types = {t["key"]: t for t in client.get(f"{api}/admin/artifact-types").json()}
    assert types["counts"]["version"] == 0
    client.post(f"{api}/admin/artifact-types", json={"key": "counts", "label": "Counts"})
    types = {t["key"]: t for t in client.get(f"{api}/admin/artifact-types").json()}
    assert types["counts"]["version"] == 1
    assert all("version" in s for s in client.get(f"{api}/admin/scopes").json())
