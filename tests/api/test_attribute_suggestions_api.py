"""The loop closes: the tool proposes, a person decides, the next run is free (6.22f).

Acceptance criterion 10 lives here — a user without admin capability can propose a
mapping when Train AI mode is on and cannot activate one — and so does the thing that
makes the whole phase worth building: a mapping accepted from a real run removes the
lookup from every later run of that configuration.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config.store import invalidate
from greenlight_ai.db import models
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]

#: The delivery whose DIRT and record layout both spell every attribute the long way.
CASE = "attribute_renamed"


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    """Keep one test's settings out of the next test's cache."""
    invalidate()
    yield
    invalidate()


def _enable_training(client: TestClient, api: str) -> None:
    """Turn Train AI mode on, which is what lets anybody record an observation."""
    response = client.post(f"{api}/admin/settings", json={"key": "training.enabled", "value": True})
    assert response.status_code == 200, response.text


class TestTheRail:
    """What a run offers, and where it came from."""

    def test_a_run_offers_what_the_record_layout_says_at_no_model_call(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
    ) -> None:
        """The record layout earns its place here, not only as one more thing to check."""
        client.post(
            f"{api}/admin/settings",
            json={"key": "llm.max_attribute_calls_per_run", "value": 0},
        )
        run_id = int(submit(CASE).json()["run_id"])
        worker.run_once()

        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert run.attribute_locate_calls == 0
            assert run.attribute_suggestions

        offered = client.get(f"{api}/admin/attribute-suggestions").json()["suggestions"]
        assert offered
        assert all(s["origin"] == "record_layout" for s in offered)
        assert all(not s["already_listed"] for s in offered)

    def test_a_delivery_with_no_layout_and_no_calls_offers_nothing(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        """Nothing proposed is the honest answer when nothing proposed anything."""
        client.post(
            f"{api}/admin/settings",
            json={"key": "llm.max_attribute_calls_per_run", "value": 0},
        )
        submit("baseline_match")
        worker.run_once()
        assert client.get(f"{api}/admin/attribute-suggestions").json()["suggestions"] == []

    def test_an_accepted_mapping_stops_asking_to_be_accepted(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        submit(CASE)
        worker.run_once()
        offered = client.get(f"{api}/admin/attribute-suggestions").json()["suggestions"]
        first = offered[0]

        accepted = client.post(
            f"{api}/admin/attribute-suggestions/accept",
            # No artifact: a name this customer uses in their DIRT is the name they
            # use everywhere, and narrowing it would leave every other check still
            # asking the question this click just answered.
            json={"wanted": first["wanted"], "found": first["found"], "origin": first["origin"]},
        )
        assert accepted.status_code == 200
        assert accepted.json()["canonical"] == first["wanted"]

        again = client.get(f"{api}/admin/attribute-suggestions").json()["suggestions"]
        listed = next(s for s in again if s["wanted"] == first["wanted"])
        assert listed["already_listed"] is True

    def test_a_spelling_another_attribute_already_owns_is_refused(
        self, client: TestClient, api: str
    ) -> None:
        """One name means one attribute; the two cannot both be right."""
        client.post(
            f"{api}/admin/attribute-suggestions/accept",
            json={"wanted": "AT01", "found": "shared_column"},
        )
        clash = client.post(
            f"{api}/admin/attribute-suggestions/accept",
            json={"wanted": "AT02", "found": "shared_column"},
        )
        assert clash.status_code == 422
        assert "already belongs to" in clash.json()["detail"]


class TestAnObservationAnybodyMayWrite:
    """Acceptance criterion 10."""

    def test_a_user_may_propose_a_mapping_while_train_ai_mode_is_on(
        self, client: TestClient, api: str, factory: sessionmaker[Session]
    ) -> None:
        """The person who reads the DIRT every week is the one who knows."""
        _enable_training(client, api)
        response = client.post(
            f"{api}/observations",
            json={
                "kind": "attribute_mapping",
                "statement": "This customer's DIRT always calls AT01 the long way.",
                "mapping": {
                    "attribute": "AT01",
                    "spelling": "debsc_burs_atyrt_at01_1",
                    "artifact": "dirt",
                },
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["kind"] == "attribute_mapping"
        assert body["mapping"]["attribute"] == "AT01"
        assert body["status"] == "new"

        # Proposing is not activating: nothing is in the dictionary yet.
        with factory() as session:
            assert session.query(models.AttributeTerm).count() == 0

    def test_a_mapping_kind_with_nothing_to_map_is_refused(
        self, client: TestClient, api: str
    ) -> None:
        """An empty approval waiting to happen."""
        _enable_training(client, api)
        response = client.post(
            f"{api}/observations",
            json={"kind": "attribute_mapping", "statement": "AT01 is spelled oddly here."},
        )
        assert response.status_code == 422

    def test_a_mapping_on_another_kind_is_refused(self, client: TestClient, api: str) -> None:
        """A field nothing reads is worse than no field."""
        _enable_training(client, api)
        response = client.post(
            f"{api}/observations",
            json={
                "kind": "note",
                "statement": "Just a note.",
                "mapping": {"attribute": "AT01", "spelling": "x"},
            },
        )
        assert response.status_code == 422

    def test_approving_writes_the_spelling_and_the_observation_says_so(
        self, client: TestClient, api: str, factory: sessionmaker[Session]
    ) -> None:
        """A person vouched for it, so it is live from here."""
        _enable_training(client, api)
        observation = client.post(
            f"{api}/observations",
            json={
                "kind": "attribute_mapping",
                "statement": "AT01 is the long column.",
                "mapping": {
                    "attribute": "AT01",
                    "spelling": "debsc_burs_atyrt_at01_1",
                    "artifact": "dirt",
                },
            },
        ).json()

        approved = client.post(f"{api}/admin/observations/{observation['id']}/approve-mapping")
        assert approved.status_code == 200
        assert approved.json()["status"] == "synthesized"

        with factory() as session:
            term = session.query(models.AttributeTerm).one()
            assert term.canonical == "AT01"
            (spelling,) = term.spellings
            assert spelling.spelling == "debsc_burs_atyrt_at01_1"
            # Provenance says a person proposed it, which is why it is live.
            assert spelling.origin == "observation"

    def test_approving_something_that_is_not_a_mapping_is_refused(
        self, client: TestClient, api: str
    ) -> None:
        _enable_training(client, api)
        observation = client.post(
            f"{api}/observations",
            json={"kind": "note", "statement": "Just a note about this delivery."},
        ).json()
        response = client.post(f"{api}/admin/observations/{observation['id']}/approve-mapping")
        assert response.status_code == 422
        assert "not an attribute mapping" in response.json()["detail"]

    def test_approving_twice_is_refused(self, client: TestClient, api: str) -> None:
        """Forward only, like every other observation state."""
        _enable_training(client, api)
        observation = client.post(
            f"{api}/observations",
            json={
                "kind": "attribute_mapping",
                "statement": "AT01 is the long column.",
                "mapping": {"attribute": "AT01", "spelling": "long_at01"},
            },
        ).json()
        client.post(f"{api}/admin/observations/{observation['id']}/approve-mapping")
        again = client.post(f"{api}/admin/observations/{observation['id']}/approve-mapping")
        assert again.status_code == 409


class TestTheLoopClosing:
    """What the whole phase is for: the next run costs less than this one."""

    def test_accepting_what_a_run_offered_resolves_the_names_on_the_next_one(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
    ) -> None:
        first = int(submit(CASE).json()["run_id"])
        worker.run_once()
        before = [f["type"] for f in client.get(f"{api}/runs/{first}/findings").json()].count(
            "attribute_not_resolved"
        )
        assert before > 0

        for suggestion in client.get(f"{api}/admin/attribute-suggestions").json()["suggestions"]:
            client.post(
                f"{api}/admin/attribute-suggestions/accept",
                json={
                    "wanted": suggestion["wanted"],
                    "found": suggestion["found"],
                    "origin": suggestion["origin"],
                },
            )

        second = int(submit(CASE, rerun_reason="the same order again").json()["run_id"])
        worker.run_once()

        after = [f["type"] for f in client.get(f"{api}/runs/{second}/findings").json()].count(
            "attribute_not_resolved"
        )
        assert after < before

        # One mapping could not be accepted, and the refusal is correct: the OSL's
        # criteria table says *score* where its attribute list says ``SCORE_V3``, and
        # both point at the same column. One name means one attribute, so the console
        # refuses the second — the person's move is to record ``score`` as another
        # spelling of ``SCORE_V3``, which is what the next test does.
        with factory() as session:
            run = session.get(models.Run, second)
            assert run is not None
            assert len(run.attribute_suggestions) == 1
            assert run.attribute_suggestions[0]["wanted"] == "score"

    def test_what_the_layout_could_not_settle_is_what_is_left_to_record(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
    ) -> None:
        """Accepting everything on offer drives the cost down to the ties, and no lower.

        ``TOT_BAL`` and ``MORT_BAL`` both resemble two of this delivery's long column
        names — they share the word ``BAL`` — so the record layout declines to propose
        either, which is the same refusal the ladder makes at every rung. A tie is not
        an answer, and a console that guessed between them would be asking a person to
        approve a comparison nobody made.

        So the remainder is not a shortfall. It is the exact set a person has to look
        at, and recording those two terms is what takes the next run to zero.
        """
        submit(CASE)
        worker.run_once()

        # ``score`` and ``SCORE_V3`` are one attribute written two ways, so they are
        # one term with two spellings rather than two terms fighting over one column.
        client.post(
            f"{api}/admin/attribute-terms",
            json={
                "canonical": "SCORE_V3",
                "spellings": [
                    {"spelling": "debsc_burs_atyrt_score_v3_1", "origin": "observation"},
                    {"spelling": "score", "origin": "observation"},
                ],
            },
        )
        for suggestion in client.get(f"{api}/admin/attribute-suggestions").json()["suggestions"]:
            if suggestion["already_listed"]:
                continue
            client.post(
                f"{api}/admin/attribute-suggestions/accept",
                json={
                    "wanted": suggestion["wanted"],
                    "found": suggestion["found"],
                    "origin": suggestion["origin"],
                },
            )

        middle = int(submit(CASE, rerun_reason="once more").json()["run_id"])
        worker.run_once()
        with factory() as session:
            run = session.get(models.Run, middle)
            assert run is not None
            spent = run.attribute_locate_calls
            assert 0 < spent <= 4

        # The two the layout could not settle, recorded by a person who looked.
        for attribute in ("TOT_BAL", "MORT_BAL"):
            client.post(
                f"{api}/admin/attribute-terms",
                json={
                    "canonical": attribute,
                    "spellings": [
                        {
                            "spelling": f"debsc_burs_atyrt_{attribute.lower()}_1",
                            "origin": "observation",
                        }
                    ],
                },
            )

        last = int(submit(CASE, rerun_reason="and once more").json()["run_id"])
        worker.run_once()
        with factory() as session:
            run = session.get(models.Run, last)
            assert run is not None
            assert run.attribute_locate_calls == 0
            assert run.attribute_suggestions == []
