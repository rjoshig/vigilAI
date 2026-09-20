"""Tests for Meaning: scoped samples, the interview, confirm → compile (Phase 6.10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from synthetic_model import build_client

from greenlight_ai.db import models

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture()
def mapped_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The interview answers from the scripted stand-in."""
    import greenlight_ai.api.routers.meaning as meaning_router

    def _build(settings: Any, cache: Any = None, **_: Any) -> Any:
        return build_client(settings, cache=cache)

    monkeypatch.setattr(meaning_router, "build_client", _build)


def _upload(
    client: TestClient, api: str, root: Path, case: dict[str, Any], scope: str = ""
) -> None:
    client.get(f"{api}/admin/artifact-types")
    files = [
        ("osl", root / case["osl"], "application/octet-stream"),
        ("config", root / case["config"], "application/json"),
    ] + [(k, root / p, XLSX) for k, p in case["reports"].items()]
    for key, path, ctype in files:
        response = client.post(
            f"{api}/admin/artifact-types/{key}/samples",
            data={"label": scope or "global", "scope_code": scope},
            files={"file": (path.name, path.read_bytes(), ctype)},
        )
        assert response.status_code == 201, response.text


def test_an_interview_needs_samples_in_scope(
    client: TestClient, api: str, mapped_model: None
) -> None:
    response = client.post(f"{api}/admin/meaning/propose", json={"scope_code": ""})
    assert response.status_code == 409
    assert "OSL sample" in response.json()["detail"]
    assert client.get(f"{api}/admin/meaning/samples").json()["missing"] == ["osl", "config"]


def test_the_interview_proposes_placed_rows_and_open_questions(
    client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any], mapped_model: None
) -> None:
    _upload(client, api, fixtures_root, cases["baseline_match"])
    result = client.post(f"{api}/admin/meaning/propose", json={"scope_code": ""})
    assert result.status_code == 200, result.text
    counts = result.json()
    assert counts["proposed"] == 2 and counts["open"] == 1 and counts["calls"] >= 5

    rows = {r["key"]: r for r in client.get(f"{api}/admin/meaning").json()}
    assert rows["input_population"]["status"] == "proposed"
    assert rows["input_population"]["config_path"] == "input.count"
    # The value column was read from the sample row, not defaulted.
    assert rows["input_population"]["report_cells"][0]["value_column"] == 3
    assert rows["ofac_excluded"]["status"] == "open"
    assert "OFAC" in rows["ofac_excluded"]["question"]
    assert (
        rows["ofac_excluded"]["compliance_suggestion"]["json_path_contains"] == "suppressions.ofac"
    )
    assert not any(r["compiled_check"] for r in rows.values())

    # Running it again updates the unconfirmed rows and skips confirmed ones.
    client.patch(f"{api}/admin/meaning/{rows['geography']['id']}", json={"status": "confirmed"})
    again = client.post(f"{api}/admin/meaning/propose", json={"scope_code": ""}).json()
    assert again["skipped_confirmed"] == 1 and again["updated"] == 2


def test_confirming_compiles_a_shadow_check_and_a_shadow_compliance_rule(
    client: TestClient,
    api: str,
    fixtures_root: Path,
    cases: dict[str, Any],
    mapped_model: None,
    factory: sessionmaker[Session],
) -> None:
    _upload(client, api, fixtures_root, cases["baseline_match"])
    client.post(f"{api}/admin/meaning/propose", json={"scope_code": ""})
    rows = {r["key"]: r for r in client.get(f"{api}/admin/meaning").json()}

    confirmed = client.patch(
        f"{api}/admin/meaning/{rows['input_population']['id']}", json={"status": "confirmed"}
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["compiled_check"] is True
    assert body["examples"][0]["value"] == "1000000"
    with factory() as session:
        check = session.execute(
            sa.select(models.CheckDefinitionRow).where(
                models.CheckDefinitionRow.name == "meaning:global:input_population"
            )
        ).scalar_one()
        assert (check.state, check.origin, check.scope) == ("shadow", "meaning", "all")
        assert check.expression == (
            "meaning_global_input_population == meaning_global_input_population_config"
        )

    # An open row with a compliance suggestion confirms into a shadow compliance rule only.
    ofac = client.patch(
        f"{api}/admin/meaning/{rows['ofac_excluded']['id']}", json={"status": "confirmed"}
    ).json()
    assert ofac["compiled_check"] is False and ofac["compiled_compliance"] is True
    with factory() as session:
        rule = session.execute(
            sa.select(models.ComplianceRuleRow).where(
                models.ComplianceRuleRow.name == "meaning:global:ofac_excluded"
            )
        ).scalar_one()
        assert (rule.state, rule.origin) == ("shadow", "meaning")
        assert rule.requirement["json_path_contains"] == "suppressions.ofac"

    # Rejecting retires both; the versions panel lists the changes.
    rejected = client.patch(
        f"{api}/admin/meaning/{rows['input_population']['id']}", json={"status": "rejected"}
    ).json()
    assert rejected["compiled_check"] is False
    listed = client.get(f"{api}/admin/versions/meaning/global").json()
    assert listed and listed[0]["summary"].startswith("input_population: rejected")


def test_programme_entries_override_global_ones_at_run_time(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    client.get(f"{api}/admin/scopes")
    for scope, text in (("", "global geography"), ("AS", "solicitation geography")):
        created = client.post(
            f"{api}/admin/meaning",
            json={
                "scope_code": scope,
                "key": "geography",
                "osl_section": "3",
                "requirement_text": text,
                "config_path": "filters[0]",
            },
        )
        assert created.status_code == 201, created.text
    created = client.post(
        f"{api}/admin/meaning",
        json={
            "scope_code": "",
            "key": "population",
            "osl_section": "2",
            "requirement_text": "global population",
        },
    )
    assert created.status_code == 201
    from greenlight_ai.meaning.render import effective_entries, meaning_lines

    with factory() as session:
        for_as = effective_entries(session, "AS")
        assert [(e.key, e.scope_code) for e in for_as] == [("population", ""), ("geography", "AS")]
        lines = meaning_lines(for_as, "Account Solicitation")
        assert lines[0].startswith("Requirement map for Account Solicitation")
        assert any("solicitation geography" in line for line in lines)
        assert not any("global geography" in line for line in lines)
        for_am = effective_entries(session, "AM")
        assert [(e.key, e.scope_code) for e in for_am] == [("population", ""), ("geography", "")]

    duplicate = client.post(f"{api}/admin/meaning", json={"scope_code": "", "key": "geography"})
    assert duplicate.status_code == 409


def test_bulk_delete_needs_the_word_and_bulk_reject_does_not(client: TestClient, api: str) -> None:
    ids = [
        client.post(f"{api}/admin/meaning", json={"scope_code": "", "key": f"k{i}"}).json()["id"]
        for i in range(3)
    ]
    rejected = client.post(f"{api}/admin/meaning/bulk", json={"ids": ids[:2], "action": "reject"})
    assert rejected.json()["changed"] == 2
    refused = client.post(f"{api}/admin/meaning/bulk", json={"ids": ids, "action": "delete"})
    assert refused.status_code == 400
    done = client.post(
        f"{api}/admin/meaning/bulk",
        json={"ids": ids + [999], "action": "delete", "confirm": "delete"},
    )
    assert done.json() == {"changed": 3, "missing": [999]}
    assert client.get(f"{api}/admin/meaning").json() == []


def test_sample_notes_reach_the_interview(
    client: TestClient,
    api: str,
    fixtures_root: Path,
    cases: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The administrator's words about a sample are the one thing the model cannot read from it."""
    import greenlight_ai.api.routers.meaning as meaning_router

    seen: list[str] = []

    def _build(settings: Any, cache: Any = None, **_: Any) -> Any:
        mock = build_client(settings, cache=cache)
        original = mock.complete

        def complete(system: str, user: str, *args: Any, **kwargs: Any) -> Any:
            seen.append(user)
            return original(system, user, *args, **kwargs)

        mock.complete = complete  # type: ignore[method-assign]
        return mock

    monkeypatch.setattr(meaning_router, "build_client", _build)
    _upload(client, api, fixtures_root, cases["baseline_match"])
    types = {t["key"]: t for t in client.get(f"{api}/admin/artifact-types").json()}
    for key, notes in (
        ("osl", "Solicitation OSLs put geography in section 3."),
        ("config", "filters[0] is always the state list."),
    ):
        sample_id = types[key]["samples"][0]["id"]
        assert (
            client.patch(
                f"{api}/admin/artifact-types/{key}/samples/{sample_id}", json={"notes": notes}
            ).status_code
            == 200
        )
    assert client.post(f"{api}/admin/meaning/propose", json={"scope_code": ""}).status_code == 200
    assert seen
    assert all("Administrator's notes on this OSL: Solicitation OSLs" in prompt for prompt in seen)
    assert all("filters[0] is always the state list" in prompt for prompt in seen)
