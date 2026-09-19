"""Standing notes on a configuration (ADR-024).

A note is guidance for every future run of its configuration and an observation in
the admin queue at once. It never enforces anything on its own.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config.store import invalidate
from greenlight_ai.db import models
from greenlight_ai.pipeline.guidance import RunGuidance, preamble

Submit = Callable[..., Any]


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    invalidate()
    yield
    invalidate()


def _note(client: TestClient, api: str, config_id: str, text: str) -> Any:
    return client.post(f"{api}/configs/{config_id}/notes", json={"statement": text})


def test_a_note_can_be_written_with_train_ai_mode_off(client: TestClient, api: str) -> None:
    """A note is guidance about a configuration, not training input."""
    assert client.get(f"{api}/training/config").json() == {"enabled": False}
    response = _note(client, api, "CFG-1", "Score band A means 700 and above for this config.")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "config_note"
    assert body["configuration_id"] == "CFG-1"
    assert body["is_active"] is True
    assert body["author"] == "John Doe"


def test_a_note_containing_personal_data_is_refused(client: TestClient, api: str) -> None:
    assert _note(client, api, "CFG-1", "Account 123-45-6789 is special.").status_code == 422


def test_a_note_reaches_the_next_run_of_its_configuration_and_no_other(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    submit: Submit,
    cases: dict[str, Any],
) -> None:
    """The snapshot on the run is what the model was told, and it names the configuration."""
    config_id = cases["geography_extra_state"]["configuration_id"]
    _note(client, api, config_id, "Treat missing state codes as a high-severity gap.")
    _note(client, api, "SOME-OTHER-CONFIG", "This one must not leak across.")

    assert submit().status_code == 201
    with factory() as session:
        run = session.execute(sa.select(models.Run)).scalars().one()
    assert run.config_notes_snapshot == ["Treat missing state codes as a high-severity gap."]

    detail = client.get(f"{api}/runs/{run.id}").json()
    assert detail["config_notes"] == ["Treat missing state codes as a high-severity gap."]


def test_the_note_is_background_in_the_prompt_never_a_requirement() -> None:
    text = preamble(RunGuidance(config_notes=("Band A is 700 and above.",)))
    assert "A note on this configuration, as background: Band A is 700 and above." in text
    assert "background rather than a requirement" in text
    assert preamble(RunGuidance(config_notes=("   ",))) == ""


def test_switching_a_note_off_stops_it_applying_and_keeps_the_text(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    submit: Submit,
    cases: dict[str, Any],
) -> None:
    config_id = cases["geography_extra_state"]["configuration_id"]
    note = _note(client, api, config_id, "Applies until switched off.").json()
    off = client.post(f"{api}/config-notes/{note['id']}/active?is_active=false")
    assert off.status_code == 200 and off.json()["is_active"] is False

    assert submit().status_code == 201
    with factory() as session:
        run = session.execute(sa.select(models.Run)).scalars().one()
    assert run.config_notes_snapshot == []

    kept = client.get(f"{api}/configs/{config_id}/notes?include_inactive=true").json()
    assert [n["statement"] for n in kept] == ["Applies until switched off."]
    assert client.get(f"{api}/configs/{config_id}/notes").json() == []


def test_editing_keeps_the_earlier_wording(client: TestClient, api: str) -> None:
    note = _note(client, api, "CFG-1", "First wording.").json()
    edited = client.patch(f"{api}/config-notes/{note['id']}", json={"statement": "Second wording."})
    assert edited.status_code == 200
    body = edited.json()
    assert body["statement"] == "Second wording."
    assert body["version"] == 2
    assert body["revisions"][0]["statement"] == "First wording."
    assert body["editable"] is True


def test_a_note_shows_in_the_admin_queue_as_a_configuration_comment(
    client: TestClient, api: str
) -> None:
    client.post(f"{api}/admin/settings", json={"key": "training.enabled", "value": True})
    _note(client, api, "CFG-9", "This configuration excludes closed accounts.")
    queue = client.get(f"{api}/observations?kind=config_note").json()
    assert len(queue) == 1
    assert queue[0]["configuration_id"] == "CFG-9"
    assert queue[0]["anchors"][0] == {
        "kind": "config_path",
        "artifact": "",
        "sheet": "",
        "cell": "",
        "field": "",
        "reference": "CFG-9",
        "value": "",
    }


def test_a_rule_learned_from_a_note_is_scoped_to_that_configuration(
    factory: sessionmaker[Session],
) -> None:
    """The point of writing the note there is that the rule stays there."""
    from greenlight_ai.db.repository import load_admin_config
    from greenlight_ai.training.synthesis import _scope_for

    with factory() as session:
        note = models.TrainingObservation(
            kind="config_note", configuration_id="CFG-7", statement="x", scope_hint="customer"
        )
        session.add(note)
        session.add(
            models.FieldConstraint(
                field="state",
                constraint="not_blank",
                value={},
                scope="config:CFG-7",
                state="active",
            )
        )
        session.commit()
        assert _scope_for([note]) == "config:CFG-7"

        assert len(load_admin_config(session, "Any Co", "CFG-7").field_constraints) == 1
        assert len(load_admin_config(session, "Any Co", "CFG-8").field_constraints) == 0


def test_the_frozen_report_shows_the_notes_the_model_was_given(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    submit: Submit,
    worker: Any,
    cases: dict[str, Any],
    seed_aliases: None,
) -> None:
    """Context that shaped the findings must be on the page with them."""
    config_id = cases["geography_extra_state"]["configuration_id"]
    _note(client, api, config_id, "Extra states are expected in this configuration.")
    run_id = submit().json()["run_id"]
    worker.run_once()
    findings = client.get(f"{api}/runs/{run_id}/findings").json()
    for finding in findings:
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "confirmed", "review_note": "ok"},
        )
    assert client.post(f"{api}/runs/{run_id}/finalize").status_code == 201
    html = client.get(f"{api}/runs/{run_id}/report").text
    assert "Extra states are expected in this configuration." in html
