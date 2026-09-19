"""Tests for validation guides over the API and through a run (Phase 6.8b)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.worker.app import Worker

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ACCEPTS = {
    "id": "accepts",
    "locator": {"kind": "label", "sheet": "Flow", "label": "Input", "value_column": 3},
    "meaning": "the input population",
    "osl_section": "2",
    "osl_phrase": "input population",
    "config_path": "input.count",
    "validate": "the report's input must equal the configured count",
    "comparison": "equals",
}

EXPLANATION_ONLY = {
    "id": "rejects",
    "locator": {"kind": "label", "sheet": "Flow", "label": "Rejects", "value_column": 3},
    "meaning": "how many records were rejected",
}


def _upload_counts(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    path = fixtures_root / cases["baseline_match"]["reports"]["counts"]
    response = client.post(
        f"{api}/admin/artifact-types/counts/samples",
        data={"label": "2025"},
        files={"file": ("counts.xlsx", path.read_bytes(), XLSX)},
    )
    assert response.status_code == 201, response.text


def _save_guide(client: TestClient, api: str, entries: list[dict[str, Any]]) -> Any:
    return client.put(f"{api}/admin/artifact-types/counts/guide", json={"entries": entries})


def test_examples_fill_from_the_samples_and_a_concrete_entry_becomes_a_shadow_check(
    client: TestClient,
    api: str,
    fixtures_root: Path,
    cases: dict[str, Any],
    factory: sessionmaker[Session],
) -> None:
    client.get(f"{api}/admin/artifact-types")
    _upload_counts(client, api, fixtures_root, cases)
    saved = _save_guide(client, api, [ACCEPTS, EXPLANATION_ONLY])
    assert saved.status_code == 200, saved.text
    guide = saved.json()["guide"]
    assert [entry["id"] for entry in guide] == ["accepts", "rejects"]
    assert guide[0]["examples"] == [
        {"sample_id": guide[0]["examples"][0]["sample_id"], "label": "2025", "value": "1000000"}
    ]
    assert guide[1]["examples"][0]["value"] == "820776"

    checks = client.get(f"{api}/admin/checks").json()
    compiled = [c for c in checks if c["name"].startswith("guide:counts:")]
    assert [c["name"] for c in compiled] == ["guide:counts:accepts"]
    assert compiled[0]["is_active"] is False
    with factory() as session:
        row = session.execute(
            sa.select(models.CheckDefinitionRow).where(
                models.CheckDefinitionRow.name == "guide:counts:accepts"
            )
        ).scalar_one()
        assert (row.state, row.origin) == ("shadow", "guide")
        assert row.expression == "guide_counts_accepts == guide_counts_accepts_config"
        names = set(session.execute(sa.select(models.NamedValueRow.name)).scalars())
    assert {"guide_counts_accepts", "guide_counts_accepts_config"} <= names

    # The guide is versioned with its artifact type.
    listed = client.get(f"{api}/admin/versions/artifact-type/counts").json()
    assert listed[0]["summary"] == "guide edited"
    assert len(listed[0]["snapshot"]["guide"]) == 2


def test_removing_the_entry_retires_its_check_and_bringing_it_back_revives_it(
    client: TestClient,
    api: str,
    fixtures_root: Path,
    cases: dict[str, Any],
    factory: sessionmaker[Session],
) -> None:
    client.get(f"{api}/admin/artifact-types")
    _upload_counts(client, api, fixtures_root, cases)
    _save_guide(client, api, [ACCEPTS])
    _save_guide(client, api, [EXPLANATION_ONLY])
    with factory() as session:
        row = session.execute(
            sa.select(models.CheckDefinitionRow).where(
                models.CheckDefinitionRow.name == "guide:counts:accepts"
            )
        ).scalar_one()
        assert row.state == "deleted"
    _save_guide(client, api, [ACCEPTS])
    with factory() as session:
        row = session.execute(
            sa.select(models.CheckDefinitionRow).where(
                models.CheckDefinitionRow.name == "guide:counts:accepts"
            )
        ).scalar_one()
        assert row.state == "shadow"


def test_duplicate_entry_ids_are_refused(client: TestClient, api: str) -> None:
    client.get(f"{api}/admin/artifact-types")
    assert _save_guide(client, api, [ACCEPTS, ACCEPTS]).status_code == 422
    assert (
        client.put(f"{api}/admin/artifact-types/nope/guide", json={"entries": []}).status_code
        == 404
    )


def test_a_run_shows_the_model_the_guide_and_the_shadow_check_fires(
    client: TestClient,
    api: str,
    fixtures_root: Path,
    cases: dict[str, Any],
    submit: Callable[..., Any],
    worker: Worker,
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance criterion 2: the next run was given the guide and a shadow check exists."""
    import greenlight_ai.worker.runner as runner

    built: list[Any] = []
    original = runner.build_client

    def _capture(*args: Any, **kwargs: Any) -> Any:
        built.append(original(*args, **kwargs))
        return built[-1]

    monkeypatch.setattr(runner, "build_client", _capture)

    client.get(f"{api}/admin/artifact-types")
    _upload_counts(client, api, fixtures_root, cases)
    # Accepts (179,224) against input.count (1,000,000): a comparison that fails, so
    # the compiled check produces a finding, and a shadow one, because it is new.
    disagreeing = {**ACCEPTS, "locator": {**ACCEPTS["locator"], "label": "Accepts"}}
    _save_guide(client, api, [disagreeing])

    run_id = submit("baseline_match").json()["run_id"]
    for _ in range(5):
        if not worker.run_once():
            break
    detail = client.get(f"{api}/runs/{run_id}").json()
    assert detail["status"] == "needs_review", detail

    trace_prompts = [user for stage, _system, user in built[-1].prompts if stage == "s4_trace"]
    assert trace_prompts
    assert all("Validation guide for Counts" in user for user in trace_prompts)
    assert all("do not compare values" in user for user in trace_prompts)

    with factory() as session:
        fired = list(
            session.execute(
                sa.select(models.Finding).where(
                    models.Finding.run_id == run_id,
                    models.Finding.title.like("%guide:counts:accepts%"),
                )
            ).scalars()
        )
    assert len(fired) == 1
    assert fired[0].shadow is True
    # Shown to no reviewer: the run's visible findings do not include it.
    visible = client.get(f"{api}/runs/{run_id}/findings").json()
    assert not [f for f in visible if "guide:counts:accepts" in f["title"]]
