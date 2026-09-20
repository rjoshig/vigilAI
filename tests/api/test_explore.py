"""Exploring the samples from the user app (Phase 6.1e).

A reviewer could only anchor an observation to a finding, which limited them to what
the tool had already noticed. The most valuable thing a person knows is usually about
something the tool said nothing about, so the samples are readable from the user side
and every part of one is something they can point at.
"""

from __future__ import annotations

import io
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models

Submit = Callable[..., Any]


def _workbook() -> bytes:
    """A tiny two-cell workbook, built in memory."""
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Summary"
    sheet.append(["Label", "Value"])
    sheet.append(["Billing count", 1234])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def catalog(factory: sessionmaker[Session]) -> None:
    """Load the shipped artifact types, which a fresh test database does not have."""
    from greenlight_ai.db import catalog as catalog_module

    with factory() as session:
        catalog_module.seed_defaults(session)
        session.commit()


@pytest.fixture()
def a_sample(client: TestClient, api: str, factory: sessionmaker[Session], catalog: None) -> int:
    """Upload one sample against the first report artifact type."""
    with factory() as session:
        artifact = (
            session.query(models.ArtifactType)
            .filter(models.ArtifactType.kind.notin_(("osl", "config")))
            .first()
        )
        assert artifact is not None, "the shipped catalog has report types"
        key = artifact.key

    response = client.post(
        f"{api}/admin/artifact-types/{key}/samples",
        files={
            "file": (
                "sample.xlsx",
                _workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"label": "A worked example"},
    )
    assert response.status_code in (200, 201), response.text
    # The upload answers with the artifact type; the sample's own id comes from the
    # list a reviewer would read.
    listed = client.get(f"{api}/samples").json()
    return int(next(a for a in listed if a["key"] == key)["samples"][-1]["id"])


def test_a_reviewer_can_list_the_samples(client: TestClient, api: str, a_sample: int) -> None:
    body = client.get(f"{api}/samples").json()

    assert body, "the uploaded sample should be listed"
    entry = next(a for a in body if any(s["id"] == a_sample for s in a["samples"]))
    assert entry["kind"], "the kind decides what a preview looks like"
    assert entry["samples"][0]["label"] == "A worked example"


def test_a_type_with_no_samples_is_left_out(client: TestClient, api: str, catalog: None) -> None:
    """The list is for finding something to point at, not for browsing the catalog."""
    assert client.get(f"{api}/samples").json() == []


def test_a_reviewer_can_read_a_sample_cell_by_cell(
    client: TestClient, api: str, a_sample: int
) -> None:
    body = client.get(f"{api}/samples/{a_sample}/preview").json()

    assert body["sample_id"] == a_sample
    cells = [cell for sheet in body["sheets"] for cell in sheet["cells"]]
    assert cells, "a populated workbook has cells"
    # The label to a cell's left is what makes it something a person can name.
    assert any(cell["label"] for cell in cells)
    assert all("cell" in cell for cell in cells)


def test_previewing_an_unknown_sample_is_a_404(client: TestClient, api: str) -> None:
    assert client.get(f"{api}/samples/9999/preview").status_code == 404


def test_the_preview_masks_what_a_real_upload_masks(
    client: TestClient, api: str, factory: sessionmaker[Session], catalog: None
) -> None:
    """A sample is a file that may hold customer data (ADR-003)."""
    import openpyxl

    with factory() as session:
        artifact = (
            session.query(models.ArtifactType)
            .filter(models.ArtifactType.kind.notin_(("osl", "config")))
            .first()
        )
        assert artifact is not None
        key = artifact.key
        session.add(models.MaskedColumn(pattern="ssn"))
        session.commit()

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sample"
    sheet.append(["SSN", "STATE"])
    sheet.append(["123-45-6789", "IL"])
    buffer = io.BytesIO()
    book.save(buffer)

    created = client.post(
        f"{api}/admin/artifact-types/{key}/samples",
        files={
            "file": (
                "s.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"label": "masking"},
    )
    assert created.status_code in (200, 201), created.text
    listed = client.get(f"{api}/samples").json()
    sample_id = next(a for a in listed if a["key"] == key)["samples"][-1]["id"]

    body = client.get(f"{api}/samples/{sample_id}/preview").json()

    values = " ".join(cell["value"] for sheet in body["sheets"] for cell in sheet["cells"])
    assert "123-45-6789" not in values
