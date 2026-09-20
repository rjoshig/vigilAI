"""The examples screen and the three promotions (Phase 6.13d, ADR-038).

An administrator could teach the model background prose and the guide and meaning maps,
and not one worked example. These tests cover what the console now offers: a library per
stage whose answers are validated against that stage's schema, a cap that makes what is
stored the same as what is shown, and the three places a person's own correction can be
promoted into an example with one click.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models

_SECTION = "9 Channel\nDeliver the accepted records by SFTP only."
_ANSWER: dict[str, Any] = {
    "requirements": [
        {
            "req_type": "other",
            "source_text": "Deliver the accepted records by SFTP only.",
            "confidence": 0.9,
        }
    ]
}


def _add(
    client: TestClient, api: str, *, stage: str = "s2_extract", **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {"stage": stage, "given": {"section": _SECTION}, "answer": _ANSWER}
    body.update(overrides)
    response = client.post(f"{api}/admin/examples", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


# --- the library -------------------------------------------------------------------------


def test_an_example_round_trips_and_is_stored_as_the_schema_dumps_it(
    client: TestClient, api: str
) -> None:
    created = _add(client, api, note="SFTP is the only channel this customer uses.")

    assert created["origin"] == "admin"
    assert created["scope"] == "everywhere"
    assert created["given"]["section"] == _SECTION
    assert created["answer"]["requirements"][0]["req_type"] == "other"

    listed = client.get(f"{api}/admin/examples", params={"stage": "s2_extract"}).json()
    assert [row["id"] for row in listed] == [created["id"]]
    assert listed[0]["note"].startswith("SFTP")


def test_an_answer_the_stage_schema_rejects_is_refused_with_the_field_named(
    client: TestClient, api: str
) -> None:
    response = client.post(
        f"{api}/admin/examples",
        json={
            "stage": "s2_extract",
            "given": {"section": _SECTION},
            "answer": {"requirements": [{"req_type": "invented"}]},
        },
    )
    assert response.status_code == 422
    assert "req_type" in response.json()["detail"]
    assert client.get(f"{api}/admin/examples").json() == [], "nothing was written"


def test_a_stage_that_takes_no_examples_is_refused(client: TestClient, api: str) -> None:
    response = client.post(
        f"{api}/admin/examples",
        json={"stage": "s9_summarize", "given": {}, "answer": {}},
    )
    assert response.status_code == 422


def test_a_fifth_active_example_is_refused_rather_than_stored_and_ignored(
    client: TestClient, api: str
) -> None:
    """A prompt carries four, so a fifth active row would look live and reach nothing."""
    for _ in range(4):
        _add(client, api)

    response = client.post(
        f"{api}/admin/examples",
        json={"stage": "s2_extract", "given": {"section": _SECTION}, "answer": _ANSWER},
    )
    assert response.status_code == 422
    assert "deactivate one first" in response.json()["detail"]

    # The same example is storable once one is out of the way.
    first = client.get(f"{api}/admin/examples").json()[0]
    assert (
        client.patch(f"{api}/admin/examples/{first['id']}", json={"is_active": False}).status_code
        == 200
    )
    _add(client, api)


def test_an_edit_revalidates_the_answer(client: TestClient, api: str) -> None:
    created = _add(client, api)
    response = client.patch(
        f"{api}/admin/examples/{created['id']}",
        json={"answer": {"requirements": [{"req_type": "nonsense"}]}},
    )
    assert response.status_code == 422

    kept = client.get(f"{api}/admin/examples").json()[0]
    assert kept["answer"]["requirements"][0]["req_type"] == "other"


def test_an_example_that_looks_like_personal_data_is_refused(client: TestClient, api: str) -> None:
    """Save is the last moment the person who pasted it can take it out (ADR-003)."""
    response = client.post(
        f"{api}/admin/examples",
        json={
            "stage": "s2_extract",
            "given": {"section": "9 Contact\nWrite to 123-45-6789 for the file."},
            "answer": _ANSWER,
        },
    )
    assert response.status_code == 422
    assert "personal data" in response.json()["detail"]
    assert client.get(f"{api}/admin/examples").json() == []


def test_a_stage_lists_its_built_in_examples_read_only(client: TestClient, api: str) -> None:
    stages = client.get(f"{api}/admin/example-stages").json()

    by_stage = {row["stage"]: row for row in stages}
    assert set(by_stage) >= {"s2_extract", "s4_trace", "admin_judgment"}
    extraction = by_stage["s2_extract"]
    assert extraction["max_examples"] == 4
    assert [field["name"] for field in extraction["fields"]] == ["section"]
    assert len(extraction["built_in"]) >= 2, "the prompt's own examples are shown above the library"
    assert extraction["built_in"][0]["shown"].startswith("Section:")


def test_every_change_writes_a_version_that_can_be_reverted(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    created = _add(client, api)
    client.patch(f"{api}/admin/examples/{created['id']}", json={"note": "reworded"})

    versions = client.get(f"{api}/admin/versions/example/s2_extract").json()
    assert len(versions) >= 2

    reverted = client.post(
        f"{api}/admin/versions/example/s2_extract/1/revert", json={"confirm": "revert"}
    )
    assert reverted.status_code == 200, reverted.text
    assert client.get(f"{api}/admin/examples").json()[0]["note"] == ""


# --- what reaches a prompt -----------------------------------------------------------------


def test_only_the_examples_in_scope_reach_a_run(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    from greenlight_ai.db import repository

    _add(client, api, scope="programme:AM")
    _add(client, api, stage="s3_describe", given={"block": "rules.state_filter"}, answer={})

    with factory() as session:
        theirs = repository.load_prompt_examples(session, programme_code="AM")
        others = repository.load_prompt_examples(session, programme_code="RS")

    assert len(theirs["s2_extract"]) == 1
    assert "s2_extract" not in others, "another programme's run is unchanged"
    assert "s3_describe" in others, "an example for everywhere still applies"


def test_a_deactivated_example_reaches_nothing(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    from greenlight_ai.db import repository

    created = _add(client, api)
    client.patch(f"{api}/admin/examples/{created['id']}", json={"is_active": False})

    with factory() as session:
        assert repository.load_prompt_examples(session) == {}


# --- promotion: nothing is promoted without a person clicking --------------------------------


def _meaning_entry(factory: sessionmaker[Session], status: str = "confirmed") -> int:
    with factory() as session:
        entry = models.MeaningEntry(
            scope_code="",
            key="geography",
            osl_section="3",
            requirement_text="Include only consumers in Illinois or Arizona.",
            config_path="rules.state_filter",
            meaning="The state filter lists the states in scope.",
            status=status,
        )
        session.add(entry)
        session.commit()
        return int(entry.id)


def test_a_confirmed_mapping_becomes_a_tracing_example(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    entry_id = _meaning_entry(factory)

    promoted = client.post(
        f"{api}/admin/examples/promote", json={"source": "meaning", "id": entry_id}
    )
    assert promoted.status_code == 201, promoted.text

    body = promoted.json()
    assert body["stage"] == "s4_trace"
    assert body["origin"] == f"promoted:meaning:{entry_id}"
    assert body["given"]["requirement"].startswith("Include only consumers")
    assert "rules.state_filter" in body["given"]["element"]
    assert body["answer"]["verdict"] == "implemented"


def test_a_mapping_nobody_confirmed_is_not_promoted(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    entry_id = _meaning_entry(factory, status="proposed")
    response = client.post(
        f"{api}/admin/examples/promote", json={"source": "meaning", "id": entry_id}
    )
    assert response.status_code == 422
    assert "confirmed" in response.json()["detail"]


def test_a_corrected_requirement_becomes_an_extraction_example(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    with factory() as session:
        run = models.Run(customer_name="Acme", order_number="ORD-9", configuration_id="CFG-1")
        session.add(run)
        session.flush()
        session.add(
            models.Rule(
                run_id=run.id,
                rule_id="R-003",
                version=2,
                source="osl",
                rule={
                    "rule_id": "R-003",
                    "source": "user",
                    "req_type": "criteria",
                    "conditions": [{"field_name": "score", "operator": ">=", "value": 755}],
                    "applies_to": "accepts",
                    "action": "accept",
                    "source_ref": "4 Credit criteria",
                    "source_text": "score | at least | 755",
                    "confidence": 1.0,
                },
            )
        )
        session.commit()
        run_id = int(run.id)

    promoted = client.post(
        f"{api}/admin/examples/promote",
        json={"source": "requirement", "id": run_id, "rule_id": "R-003"},
    )
    assert promoted.status_code == 201, promoted.text

    body = promoted.json()
    assert body["stage"] == "s2_extract"
    assert body["given"]["section"] == "score | at least | 755"
    requirement = body["answer"]["requirements"][0]
    assert requirement["req_type"] == "criteria"
    assert requirement["conditions"][0]["field_name"] == "score"
    assert "rule_id" not in requirement, "a stored rule carries more than the prompt asks for"


def test_an_approved_candidate_becomes_a_synthesis_example(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    with factory() as session:
        observation = models.TrainingObservation(
            kind="field_constraint",
            statement="The account status is never empty in the DIRT.",
            anchors=[],
            scope_hint="global",
        )
        session.add(observation)
        session.flush()
        candidate = models.RuleCandidate(
            name="account_status_not_blank",
            target_kind="field_constraint",
            body={
                "name": "account_status_not_blank",
                "target_kind": "field_constraint",
                "field": "account_status",
                "constraint": "not_blank",
                "report_kinds": ["dirt"],
            },
            source_observation_ids=[observation.id],
            status="approved",
        )
        session.add(candidate)
        session.commit()
        candidate_id = int(candidate.id)

    promoted = client.post(
        f"{api}/admin/examples/promote", json={"source": "candidate", "id": candidate_id}
    )
    assert promoted.status_code == 201, promoted.text

    body = promoted.json()
    assert body["stage"] == "training_synthesize"
    assert body["given"]["statements"].startswith("1. The account status")
    assert body["answer"]["rules"][0]["field"] == "account_status"


def test_a_candidate_still_in_draft_is_not_promoted(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    with factory() as session:
        candidate = models.RuleCandidate(name="draft", target_kind="check", status="draft")
        session.add(candidate)
        session.commit()
        candidate_id = int(candidate.id)

    response = client.post(
        f"{api}/admin/examples/promote", json={"source": "candidate", "id": candidate_id}
    )
    assert response.status_code == 422


def test_promotion_refuses_a_source_that_does_not_exist(client: TestClient, api: str) -> None:
    for source in ("meaning", "candidate"):
        assert (
            client.post(
                f"{api}/admin/examples/promote", json={"source": source, "id": 9999}
            ).status_code
            == 404
        )


def test_an_example_is_audited_so_its_arrival_is_explainable(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _add(client, api)
    with factory() as session:
        actions = set(session.execute(sa.select(models.AuditLog.action)).scalars())
    assert "admin.example.added" in actions
