"""The reviewer's loop closes (Phase 6.13b).

An author who cannot see what became of what they wrote stops writing; a reviewer who
cannot see that a finding exists because a colleague wrote a sentence cannot judge it.
Both were true before this milestone. The outcome is read from the rule tables rather
than written, so it can never say "approved" about a rule that has since gone live or
been disabled.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config.store import invalidate
from greenlight_ai.db import models


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
            "kind": "field_constraint",
            "statement": statement,
            "anchors": [{"kind": "report_field", "artifact": "dirt", "field": "account_status"}],
            "scope_hint": "global",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _mine(client: TestClient, api: str, observation_id: int) -> dict[str, Any]:
    rows = client.get(f"{api}/observations", params={"mine": "true"}).json()
    return next(row for row in rows if row["id"] == observation_id)


# --- the author sees the whole chain ------------------------------------------------------


def test_the_author_follows_an_observation_from_waiting_to_live(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    observation = _observe(client, api, "The account status is never empty in the DIRT.")
    assert _mine(client, api, observation)["outcome"] == "waiting"

    drafted = client.post(f"{api}/admin/candidates", json={"observation_ids": [observation]})
    assert drafted.status_code == 201, drafted.text
    candidate = next(c for c in drafted.json() if c["status"] == "draft")
    assert _mine(client, api, observation)["outcome"] == "drafted"

    approved = client.post(f"{api}/admin/candidates/{candidate['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    seen = _mine(client, api, observation)
    assert seen["outcome"] == "approved", "the rule exists and is in shadow"
    assert seen["rule_ref"].startswith("field_constraint:")
    assert seen["rule_state"] == "shadow"
    assert "account_status" in seen["rule_summary"]

    kind, _, rule_id = seen["rule_ref"].partition(":")
    activated = client.post(
        f"{api}/admin/rules/{kind}/{rule_id}/action",
        json={"action": "activate", "confirm": "activate"},
    )
    assert activated.status_code == 200, activated.text
    assert _mine(client, api, observation)["outcome"] == "live"

    disabled = client.post(
        f"{api}/admin/rules/{kind}/{rule_id}/action",
        json={"action": "disable", "confirm": "disable", "note": "too noisy"},
    )
    assert disabled.status_code == 200, disabled.text
    assert _mine(client, api, observation)["outcome"] == "disabled"


def test_a_rejected_candidate_tells_the_author_why(client: TestClient, api: str) -> None:
    observation = _observe(client, api, "The account status is never empty in the DIRT.")
    drafted = client.post(f"{api}/admin/candidates", json={"observation_ids": [observation]})
    candidate = next(c for c in drafted.json() if c["status"] == "draft")

    rejected = client.post(
        f"{api}/admin/candidates/{candidate['id']}/reject",
        json={"reason": "covered by the alias table already"},
    )
    assert rejected.status_code == 200, rejected.text

    seen = _mine(client, api, observation)
    assert seen["outcome"] == "rejected"
    assert seen["outcome_note"] == "covered by the alias table already"


# --- a finding says where it came from ---------------------------------------------------


def _learned_rule_and_finding(factory: sessionmaker[Session], *, shadow: bool) -> tuple[int, int]:
    """A learned field constraint and one finding it produced, written directly."""
    with factory() as session:
        run = models.Run(customer_name="Acme", order_number="ORD-1", configuration_id="CFG-1")
        session.add(run)
        session.flush()
        rule = models.FieldConstraint(
            field="account_status",
            constraint="not_blank",
            value={},
            report_kinds=["dirt"],
            severity="high",
            reasoning="Learned from a reviewer.",
            scope="everywhere",
            state="shadow" if shadow else "active",
            origin="learned",
            candidate_id=42,
        )
        session.add(rule)
        session.flush()
        finding = models.Finding(
            run_id=run.id,
            finding_id="F-01",
            type="report_violates_rule",
            severity="high",
            title="account_status is blank in 3 rows",
            detail="",
            leg="config_reports",
            rule_ref=f"field_constraint:{rule.id}",
            shadow=shadow,
            evidence={},
        )
        session.add(finding)
        session.commit()
        return int(run.id), int(finding.id)


def test_a_finding_from_a_learned_rule_says_so(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    run_id, _ = _learned_rule_and_finding(factory, shadow=False)

    findings = client.get(f"{api}/runs/{run_id}/findings").json()

    assert len(findings) == 1
    assert findings[0]["origin"] == "learned"
    assert findings[0]["rule_name"] == "account_status"
    assert "not_blank" in findings[0]["rule_summary"]


def test_a_finding_with_no_rule_behind_it_is_built_in(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    with factory() as session:
        run = models.Run(customer_name="Acme", order_number="ORD-2", configuration_id="CFG-1")
        session.add(run)
        session.flush()
        session.add(
            models.Finding(
                run_id=run.id,
                finding_id="F-01",
                type="value_mismatch",
                severity="high",
                title="score threshold differs",
                detail="",
                leg="osl_config",
                rule_ref="R-002",
                evidence={},
            )
        )
        session.commit()
        run_id = int(run.id)

    findings = client.get(f"{api}/runs/{run_id}/findings").json()

    assert findings[0]["origin"] == "built_in"
    assert findings[0]["rule_summary"] == ""


# --- the rules applied to a run ------------------------------------------------------------


def test_the_rules_applied_to_a_run_name_the_silent_ones_without_their_findings(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    run_id, _ = _learned_rule_and_finding(factory, shadow=True)

    body = client.get(f"{api}/runs/{run_id}/rules").json()

    assert body["applied"] == []
    assert len(body["running_silently"]) == 1
    silent = body["running_silently"][0]
    assert silent["origin"] == "learned"
    assert silent["shadow"] is True
    assert silent["findings"] == 0, "a shadow rule is named and nothing more"
    assert client.get(f"{api}/runs/{run_id}/findings").json() == [], "reviewers see nothing"


def test_the_rules_applied_to_a_run_count_the_visible_findings(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    run_id, _ = _learned_rule_and_finding(factory, shadow=False)

    body = client.get(f"{api}/runs/{run_id}/rules").json()

    assert body["running_silently"] == []
    assert [(r["origin"], r["findings"]) for r in body["applied"]] == [("learned", 1)]


# --- an administrator sees shadow findings and can dismiss one (ADR-040) -----------------


def test_an_administrator_sees_and_dismisses_a_shadow_finding(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    run_id, finding_id = _learned_rule_and_finding(factory, shadow=True)
    with factory() as session:
        rule_id = session.execute(sa.select(models.FieldConstraint.id)).scalar_one()

    listed = client.get(f"{api}/admin/rules/field_constraint/{rule_id}/shadow-findings")
    assert listed.status_code == 200, listed.text
    assert [f["id"] for f in listed.json()] == [finding_id]
    assert listed.json()[0]["run_id"] == run_id

    dismissed = client.patch(
        f"{api}/findings/{finding_id}",
        json={"review_status": "false_positive", "review_note": "not a real problem in shadow"},
    )
    assert dismissed.status_code == 200, dismissed.text

    rules = client.get(f"{api}/admin/rules", params={"state": "shadow"}).json()
    ours = next(r for r in rules if r["id"] == rule_id)
    assert ours["fired"] == 1
    assert ours["dismissed"] == 1, "dismissal in shadow is what makes precision knowable"


def test_an_unknown_rule_kind_has_no_shadow_findings(client: TestClient, api: str) -> None:
    assert client.get(f"{api}/admin/rules/spell/1/shadow-findings").status_code == 404
