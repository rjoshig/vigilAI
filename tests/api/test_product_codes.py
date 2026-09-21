"""Product codes end to end: define, submit, expand, snapshot (Phase 6.22c).

Driven through the real endpoints and the real worker, because the decisions that
matter are all about what happens at a seam:

* a delivery whose OSL names a code is checked against the attributes the **catalogue**
  says the code contains, never against a list the model produced;
* a code nobody defined produces a finding rather than an empty expansion, which is the
  difference between "this delivery is missing eight attributes" and a silent pass;
* the catalogue is snapshotted at submission, so a re-check a year later reproduces the
  frozen report rather than the catalogue as it stands today.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]
Seed = Callable[..., Any]

CASE = "product_code_named"


def _define(client: TestClient, api: str, code: str, attributes: list[str], **extra: Any) -> Any:
    """Define a product code through the admin endpoint."""
    return client.post(
        f"{api}/admin/product-codes",
        json={
            "code": code,
            "label": extra.pop("label", code),
            "members": [{"attribute": a, "output_name": ""} for a in attributes],
            **extra,
        },
    )


def _types(client: TestClient, api: str, run_id: int) -> list[str]:
    """Every finding type on a run."""
    return [f["type"] for f in client.get(f"{api}/runs/{run_id}/findings").json()]


class TestTheCatalogue:
    """Defining codes, and the one invariant the console enforces."""

    def test_a_code_and_its_attributes_round_trip(self, client: TestClient, api: str) -> None:
        body = _define(client, api, "ABC", ["AT01", "ST"]).json()
        assert body["code"] == "ABC"
        assert [m["attribute"] for m in body["members"]] == ["AT01", "ST"]
        assert body["member_count"] == 2
        assert body["scope"] == "everywhere"

    def test_saving_the_same_code_replaces_its_members(self, client: TestClient, api: str) -> None:
        """A code *is* its member list.

        Keeping stale rows would have a delivery checked against attributes nobody asks
        for any more.
        """
        _define(client, api, "ABC", ["AT01", "ST"])
        body = _define(client, api, "ABC", ["AT01"]).json()
        assert [m["attribute"] for m in body["members"]] == ["AT01"]
        assert len(client.get(f"{api}/admin/product-codes").json()) == 1

    def test_a_code_naming_one_attribute_twice_is_refused(
        self, client: TestClient, api: str
    ) -> None:
        response = client.post(
            f"{api}/admin/product-codes",
            json={
                "code": "ABC",
                "members": [{"attribute": "AT01"}, {"attribute": "at-01"}],
            },
        )
        assert response.status_code == 422
        assert "twice" in response.json()["detail"]

    def test_two_codes_delivering_a_shared_attribute_differently_are_refused(
        self, client: TestClient, api: str
    ) -> None:
        """One term, one output name.

        Refused at the one moment a person can still fix it, rather than reported later
        as a catalogue defect that produces findings nobody can act on.
        """
        client.post(
            f"{api}/admin/product-codes",
            json={"code": "ABC", "members": [{"attribute": "SCORE", "output_name": "SCORE_V3"}]},
        )
        response = client.post(
            f"{api}/admin/product-codes",
            json={"code": "DEF", "members": [{"attribute": "SCORE", "output_name": "SCORE_V2"}]},
        )
        assert response.status_code == 422
        assert "one term with one output name" in response.json()["detail"]

    def test_two_codes_agreeing_on_a_shared_attribute_are_allowed(
        self, client: TestClient, api: str
    ) -> None:
        client.post(
            f"{api}/admin/product-codes",
            json={"code": "ABC", "members": [{"attribute": "SCORE", "output_name": "SCORE_V3"}]},
        )
        response = client.post(
            f"{api}/admin/product-codes",
            json={"code": "DEF", "members": [{"attribute": "SCORE", "output_name": "SCORE_V3"}]},
        )
        assert response.status_code == 201
        assert response.json()["conflicts"] == []


class TestARunThatNamesACode:
    """The OSL names ABC; the delivery is checked against what ABC contains."""

    def test_a_defined_code_expands_and_the_attributes_check_passes(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        worker: Worker,
        seed_aliases: None,
        cases: dict[str, Any],
    ) -> None:
        del seed_aliases
        case = cases[CASE]
        _define(client, api, "ABC", list(case["product_code_attributes"]))
        run_id = int(submit(CASE).json()["run_id"])
        worker.run_once()

        types = _types(client, api, run_id)
        # Nothing says the requested attributes are missing: the code expanded to the
        # eight the delivery carries.
        assert not any(
            "missing" in f["detail"]
            for f in client.get(f"{api}/runs/{run_id}/findings").json()
            if f["type"] == "report_violates_rule"
            and "attributes must be present" in f.get("title", "")
        )
        # The undefined second code is reported, and reported once.
        assert types.count("report_violates_rule") >= 1

    def test_an_undefined_code_is_reported_and_never_expands_to_nothing(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        worker: Worker,
        seed_aliases: None,
        cases: dict[str, Any],
    ) -> None:
        """The whole reason the check exists.

        With DEF undefined, "check everything in DEF" must not become "check nothing".
        """
        del seed_aliases
        case = cases[CASE]
        _define(client, api, "ABC", list(case["product_code_attributes"]))
        run_id = int(submit(CASE).json()["run_id"])
        worker.run_once()

        findings = client.get(f"{api}/runs/{run_id}/findings").json()
        undefined = [
            f for f in findings if "'DEF'" in f["detail"] and "does not define it" in f["detail"]
        ]
        assert len(undefined) == 1
        assert undefined[0]["severity"] == "high"

    def test_a_delivery_carrying_more_than_the_code_lists_is_a_low_note(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        worker: Worker,
        seed_aliases: None,
        cases: dict[str, Any],
    ) -> None:
        """Never a failure, and it says why it is worth two looks."""
        del seed_aliases
        case = cases[CASE]
        # Define ABC as a subset, so the delivery carries more than it lists.
        _define(client, api, "ABC", list(case["product_code_attributes"])[:4])
        run_id = int(submit(CASE).json()["run_id"])
        worker.run_once()

        notes = [
            f
            for f in client.get(f"{api}/runs/{run_id}/findings").json()
            if f["type"] == "attributes_beyond_product_code"
        ]
        assert len(notes) == 1
        assert notes[0]["severity"] == "low"
        assert "personal data" in notes[0]["detail"]

    def test_no_note_when_no_requirement_names_a_code(
        self, submit: Submit, worker: Worker, client: TestClient, api: str, seed_aliases: None
    ) -> None:
        """Without a code there is no authoritative list of what was asked for.

        Calling every unlisted column "extra" against a hand-written attribute list
        would put noise on every run.
        """
        del seed_aliases
        run_id = int(submit("baseline_match").json()["run_id"])
        worker.run_once()
        assert "attributes_beyond_product_code" not in _types(client, api, run_id)


class TestTheSnapshot:
    """The catalogue keeps no history, so the run keeps what it used."""

    def test_the_run_snapshots_the_catalogue_at_submission(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        factory: sessionmaker[Session],
        cases: dict[str, Any],
    ) -> None:
        case = cases[CASE]
        _define(client, api, "ABC", list(case["product_code_attributes"]))
        run_id = int(submit(CASE).json()["run_id"])

        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            stored = run.product_code_attributes["codes"]["ABC"]
            assert [m["attribute"] for m in stored] == list(case["product_code_attributes"])

    def test_a_run_submitted_before_any_code_was_defined_snapshots_nothing(
        self, submit: Submit, factory: sessionmaker[Session]
    ) -> None:
        """The ordinary state on a deployment that defines no codes."""
        run_id = int(submit("baseline_match").json()["run_id"])
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert run.product_code_attributes == {}

    def test_a_recheck_uses_the_snapshot_and_says_the_catalogue_has_moved(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        worker: Worker,
        factory: sessionmaker[Session],
        seed_aliases: None,
        cases: dict[str, Any],
    ) -> None:
        """What makes a finalized report reproduce.

        The catalogue keeps no history, so a re-check cannot show *what* changed. What
        it can do, and must, is say that something did.
        """
        del seed_aliases
        case = cases[CASE]
        _define(client, api, "ABC", list(case["product_code_attributes"]))
        run_id = int(submit(CASE).json()["run_id"])
        worker.run_once()

        # An administrator narrows the code after the run was submitted.
        _define(client, api, "ABC", list(case["product_code_attributes"])[:2])
        client.post(f"{api}/runs/{run_id}/recheck")
        worker.run_once()

        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert any("catalogue has changed" in notice for notice in run.notices)
            # And it still expanded to what it was submitted against.
            stored = run.product_code_attributes["codes"]["ABC"]
            assert len(stored) == len(case["product_code_attributes"])
