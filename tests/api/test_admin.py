"""Tests for the admin API (Phase 4).

The headline test is the design doc's own example: the three billing and count checks
authored, tested against synthetic templates, activated, and firing on a real run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from vigilai.db import models
from vigilai.worker.app import Worker

Submit = Callable[..., Any]


@pytest.fixture()
def templates(client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]) -> None:
    """Upload a sample workbook for each report type the checks refer to."""
    case = cases["baseline_match"]
    for kind in ("billing", "counts", "dirt"):
        path = fixtures_root / case["reports"][kind]
        response = client.post(
            f"{api}/admin/templates",
            data={"report_type": kind},
            files={
                "file": (
                    f"{kind}_sample.xlsx",
                    path.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert response.status_code == 201, response.text


@pytest.fixture()
def named_values(client: TestClient, api: str, templates: None) -> None:
    """Define the pointers the design doc's example checks use."""
    pointers = [
        {
            "name": "billing_count",
            "report_type": "billing",
            "sheet": "Summary",
            "kind": "label",
            "label": "Billing count",
            "value_column": 1,
            "description": "Records billed to the customer",
        },
        {
            "name": "delivered_count",
            "report_type": "billing",
            "sheet": "Summary",
            "kind": "label",
            "label": "Delivered count",
            "value_column": 1,
            "description": "Records delivered",
        },
        {
            "name": "accepts_count",
            "report_type": "counts",
            "sheet": "Flow",
            "kind": "label",
            "label": "Accepts",
            "value_column": 3,
            "description": "Accepted records",
        },
        {
            "name": "rejects_count",
            "report_type": "counts",
            "sheet": "Flow",
            "kind": "label",
            "label": "Rejects",
            "value_column": 3,
            "description": "Rejected records",
        },
        {
            "name": "input_count",
            "report_type": "counts",
            "sheet": "Flow",
            "kind": "label",
            "label": "Input",
            "value_column": 3,
            "description": "Records entering the flow",
        },
    ]
    for pointer in pointers:
        assert client.post(f"{api}/admin/named-values", json=pointer).status_code == 201


# --- report templates -------------------------------------------------------------


def test_a_template_is_stored_with_its_sheets(
    client: TestClient, api: str, templates: None
) -> None:
    body = client.get(f"{api}/admin/templates").json()
    counts = next(t for t in body if t["report_type"] == "counts")
    assert "Flow" in counts["sheets"]


def test_an_unknown_report_type_is_rejected(client: TestClient, api: str) -> None:
    response = client.post(
        f"{api}/admin/templates",
        data={"report_type": "invoices"},
        files={"file": ("x.xlsx", b"PK", "application/vnd.ms-excel")},
    )
    assert response.status_code == 400
    assert "dirt" in response.json()["detail"]


def test_uploading_twice_replaces_rather_than_duplicates(
    client: TestClient, api: str, templates: None, fixtures_root: Path, cases: dict[str, Any]
) -> None:
    path = fixtures_root / cases["baseline_match"]["reports"]["billing"]
    client.post(
        f"{api}/admin/templates",
        data={"report_type": "billing"},
        files={"file": ("again.xlsx", path.read_bytes(), "application/vnd.ms-excel")},
    )
    billing = [
        t for t in client.get(f"{api}/admin/templates").json() if t["report_type"] == "billing"
    ]
    assert len(billing) == 1


# --- named values ------------------------------------------------------------------


def test_a_named_value_reports_what_it_resolves_to(
    client: TestClient, api: str, named_values: None
) -> None:
    """A pointer that no longer finds anything is what this screen exists to catch."""
    body = client.get(f"{api}/admin/named-values").json()
    billing = next(v for v in body if v["name"] == "billing_count")
    assert billing["resolved"] is not None
    assert int(billing["resolved"]) > 0


def test_a_pointer_that_finds_nothing_resolves_to_null(
    client: TestClient, api: str, templates: None
) -> None:
    client.post(
        f"{api}/admin/named-values",
        json={
            "name": "ghost",
            "report_type": "billing",
            "sheet": "Summary",
            "kind": "label",
            "label": "Not a label",
        },
    )
    body = client.get(f"{api}/admin/named-values").json()
    assert next(v for v in body if v["name"] == "ghost")["resolved"] is None


def test_saving_the_same_name_twice_updates_it(
    client: TestClient, api: str, named_values: None
) -> None:
    client.post(
        f"{api}/admin/named-values",
        json={
            "name": "billing_count",
            "report_type": "billing",
            "sheet": "Summary",
            "kind": "label",
            "label": "Billing count",
            "description": "edited",
        },
    )
    body = client.get(f"{api}/admin/named-values").json()
    matching = [v for v in body if v["name"] == "billing_count"]
    assert len(matching) == 1
    assert matching[0]["description"] == "edited"


def test_a_named_value_a_check_uses_cannot_be_deleted(
    client: TestClient, api: str, named_values: None
) -> None:
    """Deleting it would turn a working check into 'could not evaluate' with no cause."""
    client.post(
        f"{api}/admin/checks",
        json={
            "name": "billing_not_above_delivered",
            "expression": "billing_count <= delivered_count",
            "reasoning": "Billing must not exceed delivered.",
            "severity": "high",
        },
    )
    target = next(
        v for v in client.get(f"{api}/admin/named-values").json() if v["name"] == "billing_count"
    )
    response = client.delete(f"{api}/admin/named-values/{target['id']}")
    assert response.status_code == 409
    assert "billing_not_above_delivered" in response.json()["detail"]


def test_an_unused_named_value_can_be_deleted(
    client: TestClient, api: str, named_values: None
) -> None:
    target = next(
        v for v in client.get(f"{api}/admin/named-values").json() if v["name"] == "input_count"
    )
    assert client.delete(f"{api}/admin/named-values/{target['id']}").status_code == 204


# --- checks ---------------------------------------------------------------------------


def test_a_check_is_saved_with_its_references(
    client: TestClient, api: str, named_values: None
) -> None:
    body = client.post(
        f"{api}/admin/checks",
        json={
            "name": "billing_not_above_delivered",
            "expression": "billing_count <= delivered_count",
            "reasoning": "Billing must not exceed delivered.",
            "severity": "high",
        },
    ).json()
    assert body["version"] == 1
    assert body["references"] == ["billing_count", "delivered_count"]


def test_editing_a_check_bumps_the_version_and_retires_the_old_one(
    client: TestClient, api: str, named_values: None
) -> None:
    """A finding must always be able to say which version produced it."""
    client.post(
        f"{api}/admin/checks",
        json={"name": "counts_add_up", "expression": "accepts_count > 0"},
    )
    second = client.post(
        f"{api}/admin/checks",
        json={
            "name": "counts_add_up",
            "expression": "accepts_count + rejects_count == input_count",
        },
    ).json()
    assert second["version"] == 2

    versions = client.get(f"{api}/admin/checks").json()
    active = [c for c in versions if c["name"] == "counts_add_up" and c["is_active"]]
    assert len(active) == 1
    assert active[0]["version"] == 2


def test_an_invalid_expression_is_refused(client: TestClient, api: str) -> None:
    response = client.post(
        f"{api}/admin/checks", json={"name": "bad", "expression": "__import__('os')"}
    )
    assert response.status_code == 422


def test_an_expression_check_needs_an_expression(client: TestClient, api: str) -> None:
    assert client.post(f"{api}/admin/checks", json={"name": "empty"}).status_code == 422


def test_a_judgment_check_needs_an_instruction(client: TestClient, api: str) -> None:
    response = client.post(f"{api}/admin/checks", json={"name": "j", "kind": "judgment"})
    assert response.status_code == 422


def test_a_check_can_be_disabled_without_touching_old_findings(
    client: TestClient, api: str, named_values: None
) -> None:
    check = client.post(
        f"{api}/admin/checks",
        json={"name": "toggle_me", "expression": "accepts_count > 0"},
    ).json()
    disabled = client.patch(
        f"{api}/admin/checks/{check['id']}/active", params={"is_active": False}
    ).json()
    assert disabled["is_active"] is False
    assert disabled["version"] == check["version"]


# --- testing a check against the samples -----------------------------------------------


def test_the_three_example_checks_pass_against_the_samples(
    client: TestClient, api: str, named_values: None
) -> None:
    """The design doc's own examples, tested with no LLM call."""
    for expression in (
        "billing_count <= delivered_count",
        "billing_count >= accepts_count",
        "accepts_count + rejects_count == input_count",
    ):
        result = client.post(f"{api}/admin/checks/test", json={"expression": expression}).json()
        assert result["passed"] is True, f"{expression} → {result['detail']}"


def test_a_failing_test_shows_the_values_it_used(
    client: TestClient, api: str, named_values: None
) -> None:
    result = client.post(
        f"{api}/admin/checks/test", json={"expression": "billing_count > delivered_count"}
    ).json()
    assert result["passed"] is False
    assert "billing_count" in result["resolved"]


def test_an_unresolvable_value_is_reported_not_skipped(
    client: TestClient, api: str, named_values: None
) -> None:
    """docs/design.md: it never skips silently."""
    result = client.post(
        f"{api}/admin/checks/test", json={"expression": "mystery_value > 1"}
    ).json()
    assert result["passed"] is None
    assert "mystery_value" in result["detail"]
    assert "never a" in result["detail"]


def test_a_malformed_expression_is_reported(client: TestClient, api: str) -> None:
    result = client.post(f"{api}/admin/checks/test", json={"expression": "1 +"}).json()
    assert result["passed"] is None
    assert "not valid" in result["detail"]


def test_testing_a_check_makes_no_llm_call(
    client: TestClient, api: str, named_values: None, factory: sessionmaker[Session]
) -> None:
    client.post(f"{api}/admin/checks/test", json={"expression": "billing_count > 0"})
    with factory() as session:
        calls = session.execute(sa.select(sa.func.count()).select_from(models.LlmCall)).scalar_one()
    assert int(calls) == 0


# --- drafting a check -------------------------------------------------------------------


def test_drafting_proposes_named_values_and_an_expression(
    client: TestClient, api: str, templates: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one LLM call in the admin flow."""
    import vigilai.api.routers.admin as admin_module
    from vigilai.llm import MockClient

    proposal = json.dumps(
        {
            "named_values": [
                {
                    "name": "billing_count",
                    "report_type": "billing",
                    "sheet": "Summary",
                    "kind": "label",
                    "label": "Billing count",
                    "label_column": 0,
                    "value_column": 1,
                    "cell": "",
                    "description": "Records billed",
                }
            ],
            "expression": "billing_count <= 200000",
            "reasoning": "Billing must stay under the contracted cap.",
            "severity": "high",
        }
    )

    def build(settings: Any, **kwargs: Any) -> Any:
        client_ = MockClient(settings, **kwargs)
        client_.register_text("admin_draft_check", proposal)
        return client_

    monkeypatch.setattr(admin_module, "build_client", build)

    body = client.post(
        f"{api}/admin/checks/draft",
        json={"description": "Billing must stay under two hundred thousand records."},
    ).json()
    assert body["expression"] == "billing_count <= 200000"
    assert body["named_values"][0]["name"] == "billing_count"
    assert body["warnings"] == []


def test_a_draft_that_uses_an_undefined_value_is_flagged(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vigilai.api.routers.admin as admin_module
    from vigilai.llm import MockClient

    def build(settings: Any, **kwargs: Any) -> Any:
        client_ = MockClient(settings, **kwargs)
        client_.register_text(
            "admin_draft_check",
            json.dumps({"named_values": [], "expression": "ghost > 1", "severity": "high"}),
        )
        return client_

    monkeypatch.setattr(admin_module, "build_client", build)
    body = client.post(
        f"{api}/admin/checks/draft", json={"description": "Some rule about a ghost value."}
    ).json()
    assert any("ghost" in warning for warning in body["warnings"])


def test_a_draft_naming_an_unknown_report_is_flagged(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vigilai.api.routers.admin as admin_module
    from vigilai.llm import MockClient

    def build(settings: Any, **kwargs: Any) -> Any:
        client_ = MockClient(settings, **kwargs)
        client_.register_text(
            "admin_draft_check",
            json.dumps(
                {
                    "named_values": [
                        {
                            "name": "x",
                            "report_type": "invoices",
                            "sheet": "S",
                            "kind": "cell",
                            "cell": "A1",
                        }
                    ],
                    "expression": "x > 1",
                }
            ),
        )
        return client_

    monkeypatch.setattr(admin_module, "build_client", build)
    body = client.post(
        f"{api}/admin/checks/draft", json={"description": "A rule about an invoices report."}
    ).json()
    assert any("invoices" in warning for warning in body["warnings"])


# --- compliance, categories, reference data --------------------------------------------------


def test_a_compliance_rule_round_trips(client: TestClient, api: str) -> None:
    created = client.post(
        f"{api}/admin/compliance-rules",
        json={
            "name": "OFAC suppression",
            "json_path_contains": "suppressions.ofac",
            "reasoning": "OFAC-listed consumers must be suppressed.",
        },
    ).json()
    assert created["id"] > 0
    listed = client.get(f"{api}/admin/compliance-rules").json()
    assert listed[0]["json_path_contains"] == "suppressions.ofac"
    assert client.delete(f"{api}/admin/compliance-rules/{created['id']}").status_code == 204


def test_categories_fall_back_to_the_shipped_defaults(client: TestClient, api: str) -> None:
    """An empty table must not silently mean 'check nothing'."""
    body = client.get(f"{api}/admin/categories").json()
    assert len(body) >= 3
    assert any(c["checked"] for c in body)


def test_saving_one_category_seeds_the_rest(client: TestClient, api: str) -> None:
    """Otherwise switching one off would silently enable every other default."""
    client.post(
        f"{api}/admin/categories",
        json={"name": "Filters and select criteria", "kinds": ["filters"], "checked": False},
    )
    body = client.get(f"{api}/admin/categories").json()
    assert len(body) >= 3
    saved = next(c for c in body if c["name"] == "Filters and select criteria")
    assert saved["checked"] is False


def test_aliases_round_trip(client: TestClient, api: str) -> None:
    created = client.post(
        f"{api}/admin/aliases", json={"canonical_name": "score", "alias": "SCORE_V3"}
    ).json()
    assert client.get(f"{api}/admin/aliases").json()[0]["alias"] == "SCORE_V3"
    assert client.delete(f"{api}/admin/aliases/{created['id']}").status_code == 204


def test_masked_columns_fall_back_to_the_shipped_defaults(client: TestClient, api: str) -> None:
    """ADR-003: an empty table must never mean 'mask nothing'."""
    body = client.get(f"{api}/admin/masked-columns").json()
    assert any(column["pattern"] == "ssn" for column in body)
    assert all(column["is_default"] for column in body)


def test_adding_a_masked_column_keeps_the_defaults(client: TestClient, api: str) -> None:
    client.post(f"{api}/admin/masked-columns", json={"pattern": "ACCT_REF"})
    patterns = {column["pattern"] for column in client.get(f"{api}/admin/masked-columns").json()}
    assert "ACCT_REF" in patterns
    assert "ssn" in patterns


# --- usage -------------------------------------------------------------------------------------


def test_usage_reports_zeroes_on_an_empty_install(client: TestClient, api: str) -> None:
    body = client.get(f"{api}/admin/usage").json()
    assert body["runs_total"] == 0
    assert body["failure_rate"] == 0.0
    assert body["findings_by_type"] == {}


def test_usage_counts_a_completed_run(
    client: TestClient, api: str, submit: Submit, worker: Worker
) -> None:
    submit("geography_extra_state")
    worker.run_once()
    body = client.get(f"{api}/admin/usage").json()
    assert body["runs_total"] == 1
    assert body["tokens_total"] > 0
    assert sum(body["findings_by_type"].values()) > 0
    assert len(body["runs_per_day"]) == 1


# --- the phase-4 acceptance path -----------------------------------------------------------


def test_an_authored_check_fires_as_a_finding_on_a_real_run(
    client: TestClient, api: str, named_values: None, submit: Submit, worker: Worker
) -> None:
    """Phase 4 criterion 1: authored, tested, activated, and firing."""
    tested = client.post(
        f"{api}/admin/checks/test", json={"expression": "billing_count > delivered_count"}
    ).json()
    assert tested["passed"] is False

    client.post(
        f"{api}/admin/checks",
        json={
            "name": "impossible_billing",
            "expression": "billing_count > delivered_count",
            "reasoning": "Deliberately false, to prove an active check reaches a run.",
            "severity": "high",
        },
    )

    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()

    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    fired = [f for f in findings if "impossible_billing" in f["title"]]
    assert len(fired) == 1
    assert fired[0]["severity"] == "high"
    assert fired[0]["type"] == "cross_report_disagreement"
    assert "billing_count =" in fired[0]["detail"]


def test_a_disabled_check_does_not_fire_on_new_runs(
    client: TestClient, api: str, named_values: None, submit: Submit, worker: Worker
) -> None:
    """Phase 4 criterion 3."""
    check = client.post(
        f"{api}/admin/checks",
        json={"name": "switched_off", "expression": "billing_count > delivered_count"},
    ).json()
    client.patch(f"{api}/admin/checks/{check['id']}/active", params={"is_active": False})

    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()

    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    assert [f for f in findings if "switched_off" in f["title"]] == []


def test_a_missing_named_value_becomes_a_could_not_evaluate_finding(
    client: TestClient, api: str, templates: None, submit: Submit, worker: Worker
) -> None:
    """Phase 4 criterion 2: never a silent skip."""
    client.post(
        f"{api}/admin/named-values",
        json={
            "name": "absent_value",
            "report_type": "billing",
            "sheet": "Summary",
            "kind": "label",
            "label": "Nowhere to be found",
        },
    )
    client.post(
        f"{api}/admin/checks",
        json={"name": "needs_absent", "expression": "absent_value > 1"},
    )

    run_id = submit("baseline_match").json()["run_id"]
    worker.run_once()

    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    unresolved = [f for f in findings if f["type"] == "could_not_evaluate"]
    assert any("absent_value" in f["detail"] for f in unresolved)


def test_an_alias_added_by_an_admin_removes_the_could_not_evaluate(
    client: TestClient, api: str, submit: Submit, worker: Worker
) -> None:
    """The reference-data screen exists to fix exactly this."""
    first = submit("score_value_mismatch").json()["run_id"]
    worker.run_once()
    before = [
        f
        for f in client.get(f"{api}/runs/{first}/findings").json()
        if f["type"] == "could_not_evaluate" and "score" in f["title"]
    ]
    assert before, "expected an unresolved score check before the alias is added"

    client.post(f"{api}/admin/aliases", json={"canonical_name": "score", "alias": "SCORE_V3"})

    second = submit("score_value_mismatch", rerun_reason="alias added").json()["run_id"]
    worker.run_once()
    after = [
        f
        for f in client.get(f"{api}/runs/{second}/findings").json()
        if f["type"] == "could_not_evaluate" and "score" in f["title"]
    ]
    assert after == []
