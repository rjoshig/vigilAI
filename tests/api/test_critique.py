"""The critique pass and conflict resolution on a candidate rule (Phase 6.11g).

Code already rejects a malformed rule. The failure this guards against is a well-formed
rule that says something the person did not, and a rule approved on top of one that
already covers the same ground.
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
    """Keep one test's settings out of the next test's cache."""
    invalidate()
    yield
    invalidate()


@pytest.fixture(autouse=True)
def training_on(client: TestClient, api: str, _clean_cache: None) -> None:
    """Train AI mode has to be on for any of this to exist."""
    response = client.post(f"{api}/admin/settings", json={"key": "training.enabled", "value": True})
    assert response.status_code == 200, response.text


@pytest.fixture()
def scripted_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point synthesis at the scripted stand-in rather than a network."""
    import greenlight_ai.api.routers.training as training_router
    from synthetic_model import build_client

    monkeypatch.setattr(
        training_router, "build_client", lambda settings, **kw: build_client(settings)
    )


def _observe(client: TestClient, api: str, statement: str) -> Any:
    """File one observation."""
    return client.post(
        f"{api}/observations",
        json={
            "kind": "field_constraint",
            "statement": statement,
            "anchors": [{"kind": "report_field", "artifact": "dirt", "field": "account_status"}],
            "scope_hint": "global",
        },
    )


def _draft(client: TestClient, api: str, statement: str) -> dict[str, Any]:
    """File an observation and synthesize it into a candidate."""
    created = _observe(client, api, statement).json()
    drafted = client.post(f"{api}/admin/candidates", json={"observation_ids": [created["id"]]})
    assert drafted.status_code == 201, drafted.text
    return next(c for c in drafted.json() if c["status"] == "draft")


# --- the critique pass -------------------------------------------------------------------


def test_a_candidate_records_what_the_critique_said(
    client: TestClient, api: str, scripted_model: None
) -> None:
    candidate = _draft(client, api, "The account status is never empty in the DIRT.")

    assert candidate["critique"], "the critique ran and was kept"
    assert "faithful" in candidate["critique"]


def test_the_first_draft_is_kept_beside_what_was_stored(
    client: TestClient, api: str, scripted_model: None, factory: sessionmaker[Session]
) -> None:
    """The distance between them is the only measure of how much correcting it needs."""
    candidate = _draft(client, api, "The account status is never empty in the DIRT.")

    with factory() as session:
        row = session.get(models.RuleCandidate, candidate["id"])
        assert row is not None
        assert row.model_draft, "the model's first attempt is always kept"


def test_a_critique_that_cannot_run_leaves_the_first_draft_standing(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The critique is an improvement, not a gate."""
    import greenlight_ai.api.routers.training as training_router
    from greenlight_ai.llm.client import LLMError
    from synthetic_model import build_client

    def _client(settings: Any, **_kw: Any) -> Any:
        built = build_client(settings)

        def explode(_system: str, _user: str) -> str:
            raise LLMError("the model could not be reached")

        built.register("training_critique", explode)
        return built

    monkeypatch.setattr(training_router, "build_client", _client)

    candidate = _draft(client, api, "The account status is never empty in the DIRT.")

    assert candidate["status"] == "draft"
    assert candidate["body"]["field"] == "account_status"
    assert candidate["critique"] == {}


# --- conflicts ---------------------------------------------------------------------------


def _force_conflict(factory: sessionmaker[Session], candidate_id: int, rule_id: int) -> None:
    """Record an overlap on a candidate, as detection would."""
    with factory() as session:
        row = session.get(models.RuleCandidate, candidate_id)
        assert row is not None
        row.conflicts = [
            {"id": rule_id, "name": "An existing rule", "summary": "covers the same ground"}
        ]
        session.commit()


def test_approving_a_conflicting_candidate_without_a_resolution_is_refused(
    client: TestClient, api: str, scripted_model: None, factory: sessionmaker[Session]
) -> None:
    """Overlapping rules accumulate quietly and are very hard to untangle later."""
    candidate = _draft(client, api, "The account status is never empty in the DIRT.")
    _force_conflict(factory, candidate["id"], rule_id=1)

    refused = client.post(f"{api}/admin/candidates/{candidate['id']}/approve", json={})

    assert refused.status_code == 422
    assert "overlaps" in refused.json()["detail"]
    assert "supersede" in refused.json()["detail"]


def test_keeping_both_approves_and_leaves_the_other_rule_alone(
    client: TestClient, api: str, scripted_model: None, factory: sessionmaker[Session]
) -> None:
    candidate = _draft(client, api, "The account status is never empty in the DIRT.")
    _force_conflict(factory, candidate["id"], rule_id=1)

    approved = client.post(
        f"{api}/admin/candidates/{candidate['id']}/approve",
        json={"resolution": "keep_both", "note": "they cover different segments"},
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_superseding_disables_the_rule_it_replaces(
    client: TestClient, api: str, scripted_model: None, factory: sessionmaker[Session]
) -> None:
    """Disabled rather than deleted: reversible, and old findings still point somewhere."""
    first = _draft(client, api, "The account status is never empty in the DIRT.")
    client.post(f"{api}/admin/candidates/{first['id']}/approve", json={})
    with factory() as session:
        existing = session.execute(sa.select(models.FieldConstraint)).scalars().first()
        assert existing is not None
        existing_id = existing.id

    second = _draft(client, api, "The account status is never blank in the DIRT file.")
    _force_conflict(factory, second["id"], rule_id=existing_id)

    approved = client.post(
        f"{api}/admin/candidates/{second['id']}/approve",
        json={"resolution": "supersede", "note": "the newer wording is right"},
    )

    assert approved.status_code == 200
    with factory() as session:
        replaced = session.get(models.FieldConstraint, existing_id)
        assert replaced is not None
        assert replaced.state == "disabled"


def test_a_candidate_with_no_conflicts_needs_no_resolution(
    client: TestClient, api: str, scripted_model: None
) -> None:
    candidate = _draft(client, api, "The account status is never empty in the DIRT.")

    approved = client.post(f"{api}/admin/candidates/{candidate['id']}/approve", json={})

    assert approved.status_code == 200


# --- what already covers this, said at the moment of writing (Phase 6.1e) ----------------


def test_an_observation_carries_the_rules_that_already_cover_it(
    client: TestClient, api: str, scripted_model: None, factory: sessionmaker[Session]
) -> None:
    """Saying it now beats saying it weeks later through an administrator."""
    first = _draft(client, api, "The account status is never empty in the DIRT.")
    client.post(f"{api}/admin/candidates/{first['id']}/approve", json={})

    created = _observe(client, api, "The account status must always be filled in.").json()

    assert created["covered_by"], "an active rule on the same field should be named"
    assert created["covered_by"][0]["kind"] == "field_constraint"
    assert created["covered_by"][0]["contradicts"] is False


def test_a_statement_that_reverses_an_active_rule_is_flagged_as_a_contradiction(
    client: TestClient, api: str, scripted_model: None, factory: sessionmaker[Session]
) -> None:
    """And it is still saved: the old rule may be the one that is wrong (ADR-021)."""
    first = _draft(client, api, "The account status is never empty in the DIRT.")
    client.post(f"{api}/admin/candidates/{first['id']}/approve", json={})

    created = _observe(client, api, "The account status can be blank for closed accounts.")

    assert created.status_code == 201, "a contradiction is information, not a refusal"
    body = created.json()
    assert any(rule["contradicts"] for rule in body["covered_by"])


def test_an_observation_nothing_covers_says_nothing(
    client: TestClient, api: str, scripted_model: None
) -> None:
    """The ordinary case stays quiet."""
    created = _observe(client, api, "The account status is never empty in the DIRT.").json()

    assert created["covered_by"] == []
