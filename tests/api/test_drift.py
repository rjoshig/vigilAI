"""Tests for delivery drift over the API and on the frozen report (ADR-030)."""

from __future__ import annotations

from typing import Any, Callable

from fastapi.testclient import TestClient

from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]


def _finalize(client: TestClient, api: str, run_id: int, high_as: str = "confirmed") -> None:
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        status = high_as if finding["severity"] == "high" else "false_positive"
        client.patch(f"{api}/findings/{finding['id']}", json={"review_status": status})
    response = client.post(f"{api}/runs/{run_id}/finalize")
    assert response.status_code == 201, response.text


def test_a_first_run_has_nothing_to_compare_with(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()
    drift = client.get(f"{api}/runs/{run_id}/drift").json()
    assert drift["previous_run_id"] is None
    assert "No earlier finalized run" in drift["reason"]


def test_drift_names_new_resolved_and_carried_findings_and_the_config_paths(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    """Two runs of one configuration: the second has one new finding and one resolved."""
    first = submit(
        "score_value_mismatch", configuration_id="CFG-DRIFT", customer_name="Acme Card Services"
    ).json()["run_id"]
    worker.run_once()
    _finalize(client, api, first)  # the mismatch is marked Not OK

    second = submit(
        "geography_extra_state", configuration_id="CFG-DRIFT", customer_name="Acme Card Services"
    ).json()["run_id"]
    worker.run_once()
    drift = client.get(f"{api}/runs/{second}/drift").json()

    assert drift["previous_run_id"] == first
    assert drift["previous_verdict"] == "not_ok"
    new_types = {f["type"] for f in drift["new"]}
    resolved_types = {f["type"] for f in drift["resolved"]}
    assert "report_violates_rule" in new_types or "value_mismatch" in resolved_types
    assert "value_mismatch" in resolved_types
    assert drift["carried_not_ok"] == []
    assert drift["config"], "the two fixtures carry different configurations"
    assert all(c["path"] != "last_modified" for c in drift["config"])

    # A third run identical to the first carries its Not OK item back.
    third = submit(
        "score_value_mismatch",
        configuration_id="CFG-DRIFT",
        customer_name="Acme Card Services",
        rerun_reason="drift test",
    ).json()["run_id"]
    worker.run_once()
    _finalize(client, api, second, high_as="accepted_risk")
    drift = client.get(f"{api}/runs/{third}/drift").json()
    assert drift["previous_run_id"] == second
    assert not drift["carried_not_ok"]  # the second run's Not OK list was empty
    assert {f["type"] for f in drift["new"]} >= {"value_mismatch"}


def test_the_frozen_report_carries_the_comparison(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    first = submit(
        "score_value_mismatch", configuration_id="CFG-R", customer_name="Acme Card Services"
    ).json()["run_id"]
    worker.run_once()
    _finalize(client, api, first)
    second = submit(
        "score_value_mismatch",
        configuration_id="CFG-R",
        customer_name="Acme Card Services",
        rerun_reason="drift test",
    ).json()["run_id"]
    worker.run_once()
    _finalize(client, api, second)
    html = client.get(f"{api}/runs/{second}/report").text
    assert "Since the previous run" in html
    assert f"VR-{first:04d}" in html
    assert "Not OK item(s) from last time are back" in html
    # The first run's report, generated before any earlier run existed, has no section.
    assert "Since the previous run" not in client.get(f"{api}/runs/{first}/report").text
