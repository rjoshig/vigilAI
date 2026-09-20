"""The API-side repairs of Phase 6.13a.

Each test here failed on ``dev`` before the repair it names.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config.store import invalidate
from greenlight_ai.db import models

Submit = Callable[..., Any]


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    invalidate()
    yield
    invalidate()


@pytest.fixture(autouse=True)
def training_on(client: TestClient, api: str, _clean_cache: None) -> None:
    response = client.post(f"{api}/admin/settings", json={"key": "training.enabled", "value": True})
    assert response.status_code == 200, response.text


@pytest.fixture(autouse=True)
def scripted_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import greenlight_ai.api.routers.training as training_router
    from synthetic_model import build_client

    monkeypatch.setattr(
        training_router, "build_client", lambda settings, **kw: build_client(settings)
    )


def _observe(client: TestClient, api: str, statement: str) -> int:
    response = client.post(
        f"{api}/observations",
        json={
            "kind": "reconciliation",
            "statement": statement,
            "anchors": [{"kind": "config_path", "reference": "suppressions"}],
            "scope_hint": "global",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


# --- D3: a learned compliance rule looks for a real path ----------------------------------


def test_a_learned_compliance_rule_carries_the_path_it_looks_for(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """Approval used to write the rule's *name* as the path fragment, so it never matched."""
    observation = _observe(
        client,
        api,
        "Every configuration has to switch on the deceased suppression, even when the "
        "requirements document does not mention it.",
    )
    drafted = client.post(f"{api}/admin/candidates", json={"observation_ids": [observation]})
    assert drafted.status_code == 201, drafted.text
    candidate = next(c for c in drafted.json() if c["target_kind"] == "compliance_rule")
    assert candidate["body"]["json_path_contains"] == "suppressions.deceased"

    approved = client.post(f"{api}/admin/candidates/{candidate['id']}/approve", json={})
    assert approved.status_code == 200, approved.text

    with factory() as session:
        row = session.execute(sa.select(models.ComplianceRuleRow)).scalars().one()
        assert row.requirement["json_path_contains"] == "suppressions.deceased"
        assert row.requirement["json_path_contains"] != row.name
        assert row.state == "shadow"


# --- D15: each candidate names the statements it came from --------------------------------


def test_each_candidate_names_only_the_observations_that_produced_it(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    first = _observe(client, api, "The account status is never empty in the DIRT.")
    second = _observe(client, api, "Every configuration has to switch on the deceased suppression.")

    drafted = client.post(f"{api}/admin/candidates", json={"observation_ids": [first, second]})
    assert drafted.status_code == 201, drafted.text
    drafts = [c for c in drafted.json() if c["status"] == "draft"]
    by_kind = {c["target_kind"]: c for c in drafts}
    assert set(by_kind) == {"field_constraint", "compliance_rule"}, drafted.json()

    assert by_kind["field_constraint"]["source_observation_ids"] == [first]
    assert by_kind["compliance_rule"]["source_observation_ids"] == [second]

    with factory() as session:
        rows = {
            row.id: row for row in session.execute(sa.select(models.TrainingObservation)).scalars()
        }
    assert rows[first].candidate_id == by_kind["field_constraint"]["id"]
    assert rows[second].candidate_id == by_kind["compliance_rule"]["id"]


# --- D13: configuration notes are not "waiting for an administrator" ---------------------


def test_configuration_notes_stay_out_of_my_observations(client: TestClient, api: str) -> None:
    """A note already reaches the model; the observations page said it was waiting."""
    note = client.post(
        f"{api}/configs/CFG-7/notes",
        json={"statement": "This configuration delivers state codes as two letters."},
    )
    assert note.status_code == 201, note.text
    _observe(client, api, "The account status is never empty in the DIRT.")

    mine = client.get(f"{api}/observations", params={"mine": "true"}).json()
    kinds = {row["kind"] for row in mine}
    assert "config_note" not in kinds
    assert "reconciliation" in kinds

    asked_for = client.get(f"{api}/observations", params={"mine": "true", "kind": "config_note"})
    assert [row["kind"] for row in asked_for.json()] == ["config_note"]


# --- smaller: a bad credit date is refused, not silently ignored ---------------------------


def test_a_credit_date_that_is_not_a_date_is_refused(submit: Submit) -> None:
    """It used to become ``None`` and switch the credit-date check off for that run."""
    response = submit(credit_date="31/12/2025")

    assert response.status_code == 422
    assert "YYYY-MM-DD" in response.json()["detail"]


def test_an_iso_credit_date_is_accepted(submit: Submit) -> None:
    assert submit(credit_date="2025-12-31").status_code == 201
