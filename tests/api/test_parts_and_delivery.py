"""Several files per report type, and the delivery context (ADR-021).

The two features share a theme: a campaign is not always one file per report type,
and the tool should say so rather than quietly validating whatever arrived.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models

Submit = Callable[..., Any]


def _files(
    fixtures_root: Path, case: dict[str, Any], extra_parts: int = 0
) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Build a multipart payload, optionally repeating the field distribution."""
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        (
            "osl",
            ("osl.docx", (fixtures_root / case["osl"]).read_bytes(), "application/octet-stream"),
        ),
        (
            "config",
            ("config.json", (fixtures_root / case["config"]).read_bytes(), "application/json"),
        ),
    ]
    for kind, path in case["reports"].items():
        files.append((kind, (f"{kind}.xlsx", (fixtures_root / path).read_bytes(), xlsx)))
    for index in range(extra_parts):
        path = fixtures_root / case["reports"]["field_distribution"]
        files.append(("field_distribution", (f"fd_extra_{index}.xlsx", path.read_bytes(), xlsx)))
    return files


def test_a_slot_accepts_several_files_and_each_is_recorded_as_a_part(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    fixtures_root: Path,
    cases: dict[str, Any],
) -> None:
    """Some campaigns deliver one field distribution per segment."""
    case = cases["baseline_match"]
    response = client.post(
        f"{api}/runs",
        data={
            "customer_name": case["customer"],
            "order_number": case["order_number"],
            "configuration_id": case["configuration_id"],
            "field_distribution__label": ["north", "south", "west"],
        },
        files=_files(fixtures_root, case, extra_parts=2),
    )
    assert response.status_code == 201, response.text

    with factory() as session:
        rows = list(
            session.execute(
                sa.select(models.RunFile)
                .where(models.RunFile.kind == "field_distribution")
                .order_by(models.RunFile.part)
            ).scalars()
        )
    assert [row.part for row in rows] == [1, 2, 3]
    assert [row.part_label for row in rows] == ["north", "south", "west"]


def test_one_file_per_slot_still_records_a_single_part(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """The ordinary case is unchanged, which is what the rest of the suite relies on."""
    assert submit().status_code == 201
    with factory() as session:
        rows = list(session.execute(sa.select(models.RunFile)).scalars())
    assert all(row.part == 1 for row in rows)
    assert all(row.part_label == "" for row in rows)


def test_a_finding_names_the_part_it_came_from(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    worker: Any,
    fixtures_root: Path,
    cases: dict[str, Any],
    seed_aliases: None,
) -> None:
    """ "The field distribution is wrong" is useless when three were uploaded."""
    case = cases["geography_extra_state"]
    created = client.post(
        f"{api}/runs",
        data={
            "customer_name": case["customer"],
            "order_number": case["order_number"],
            "configuration_id": case["configuration_id"],
            "field_distribution__label": ["north", "south"],
        },
        files=_files(fixtures_root, case, extra_parts=1),
    )
    assert created.status_code == 201, created.text
    worker.run_once()

    with factory() as session:
        titles = list(session.execute(sa.select(models.Finding.title)).scalars())
    named = [title for title in titles if "north" in title or "south" in title]
    assert named, f"no finding named its part: {titles}"


# --- delivery context ---------------------------------------------------------------


def test_the_declared_deliverable_count_is_recorded(
    client: TestClient, api: str, factory: sessionmaker[Session], submit: Submit
) -> None:
    """Asking is only useful if the answer is kept."""
    assert (
        submit(
            deliverable_count="4", outputs_validated="4", delivery_notes="two states"
        ).status_code
        == 201
    )
    with factory() as session:
        run = session.execute(sa.select(models.Run)).scalars().one()
    assert run.deliverable_count == 4
    assert run.outputs_validated == 4
    assert run.delivery_notes == "two states"


def test_declaring_more_outputs_than_were_uploaded_is_a_finding(
    client: TestClient, api: str, factory: sessionmaker[Session], worker: Any, submit: Submit
) -> None:
    """A count the model is merely told is a count nobody verifies."""
    assert submit(deliverable_count="12", outputs_validated="12").status_code == 201
    worker.run_once()
    with factory() as session:
        findings = list(
            session.execute(
                sa.select(models.Finding).where(models.Finding.type == "deliverables_missing")
            ).scalars()
        )
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert "12" in findings[0].title


def test_saying_nothing_about_deliverables_adds_no_finding(
    client: TestClient, api: str, factory: sessionmaker[Session], worker: Any, submit: Submit
) -> None:
    """Unstated is not the same as wrong."""
    assert submit().status_code == 201
    worker.run_once()
    with factory() as session:
        types = set(session.execute(sa.select(models.Finding.type)).scalars())
    assert "deliverables_missing" not in types
