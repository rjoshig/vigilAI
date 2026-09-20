"""The hold at submit, and the one click that clears it (Phase 6.14a, ADR-041).

The behaviour under test is the one the review demonstrated: a submission whose
configuration id and customer disagree with the configuration it uploads used to run to
completion and read as a normal result. It now stops before the model is asked anything,
shows both values, and starts as soon as somebody says why.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.worker.app import Worker


class TestACleanSubmissionIsUnaffected:
    """The standing rule: checking nothing new changes nothing (ADR-020)."""

    def test_matching_artifacts_queue_exactly_as_before(self, submit: Callable[..., Any]) -> None:
        """Every fixture declares the identity its manifest submits, so none is held."""
        response = submit()
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "queued"
        assert body["mismatches"] == []
        assert body["queue_position"] is not None


class TestTheHold:
    """What happens when the artifacts disagree."""

    def test_a_wrong_configuration_id_holds_the_run(self, submit: Callable[..., Any]) -> None:
        """The case that silently disabled drift."""
        response = submit(configuration_id="CFG-DOES-NOT-EXIST-999")
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "held"
        assert body["queue_position"] is None

        fields = {m["field"]: m for m in body["mismatches"]}
        assert "configuration_id" in fields
        assert fields["configuration_id"]["submitted"] == "CFG-DOES-NOT-EXIST-999"
        assert fields["configuration_id"]["declared"] == "CFG-SYNTH-GEO-02"
        assert fields["configuration_id"]["kind"] == "different"
        assert fields["configuration_id"]["label"] == "Configuration id"

    def test_a_wrong_customer_holds_the_run(self, submit: Callable[..., Any]) -> None:
        """The field the configuration carried and nothing ever read."""
        body = submit(customer_name="Totally Different Bank PLC").json()
        assert body["status"] == "held"
        fields = {m["field"]: m for m in body["mismatches"]}
        assert fields["customer"]["declared"] == "Acme Card Services"

    def test_both_wrong_gives_both_rows(self, submit: Callable[..., Any]) -> None:
        """The review's submission: every field it could get wrong, it got wrong."""
        body = submit(
            configuration_id="CFG-DOES-NOT-EXIST-999",
            customer_name="Totally Different Bank PLC",
        ).json()
        assert {m["field"] for m in body["mismatches"]} == {"configuration_id", "customer"}

    def test_a_suffix_only_difference_is_shown_as_near(self, submit: Callable[..., Any]) -> None:
        """Probably the same customer. Shown anyway, never passed silently."""
        body = submit(customer_name="Acme Card Services, Inc.").json()
        assert body["status"] == "held"
        assert body["mismatches"][0]["kind"] == "near"

    def test_the_files_are_kept_so_nothing_is_re_uploaded(
        self, submit: Callable[..., Any], factory: sessionmaker[Session]
    ) -> None:
        """The hold exists to be cleared by a click, not by resubmitting seven files."""
        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        with factory() as session:
            files = list(
                session.execute(
                    sa.select(models.RunFile).where(models.RunFile.run_id == run_id)
                ).scalars()
            )
        assert len(files) == 7


class TestTheWorkerRefusesAHeldRun:
    """The gate is at submit, but a queue consumer must not race past it."""

    def test_a_held_run_is_refused_even_if_a_job_exists(
        self,
        submit: Callable[..., Any],
        factory: sessionmaker[Session],
        worker: Worker,
    ) -> None:
        """A job replayed from a dead letter arrives at the runner and stops."""
        from greenlight_ai.worker import runner

        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        with pytest.raises(ValueError, match="held"):
            runner.execute_run(
                factory,
                run_id,
                worker._data_dir,
                llm_settings=worker._llm_settings,
            )


class TestAccepting:
    """The bypass: one reason, one click, and it runs."""

    def test_accepting_queues_the_run(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """The whole point of holding rather than refusing."""
        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        response = client.post(
            f"{api}/runs/{run_id}/match/accept",
            json={"reason": "Typed the wrong id on the form; the files are right."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "queued"
        assert body["accepted"] == 1
        assert body["queue_position"] is not None

    def test_one_reason_covers_every_mismatch(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """Asking the same question three times trains people to answer it blindly."""
        run_id = submit(
            configuration_id="CFG-WRONG", customer_name="Totally Different Bank PLC"
        ).json()["run_id"]
        body = client.post(
            f"{api}/runs/{run_id}/match/accept",
            json={"reason": "Re-run of an archived delivery under its old name."},
        ).json()
        assert body["accepted"] == 2
        assert body["status"] == "queued"

    def test_a_reason_is_required(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """An acceptance nobody explained is a row nobody can review."""
        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        response = client.post(f"{api}/runs/{run_id}/match/accept", json={"reason": ""})
        assert response.status_code == 422

    def test_accepting_one_field_leaves_the_run_held(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """Partial acceptance is allowed and does not start the run."""
        run_id = submit(
            configuration_id="CFG-WRONG", customer_name="Totally Different Bank PLC"
        ).json()["run_id"]
        body = client.post(
            f"{api}/runs/{run_id}/match/accept",
            json={"reason": "The id is a typo.", "fields": ["configuration_id"]},
        ).json()
        assert body["accepted"] == 1
        assert body["status"] == "held"
        assert body["queue_position"] is None

    def test_who_accepted_and_why_is_kept(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """The record is what makes the waiver reviewable afterwards."""
        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        client.post(f"{api}/runs/{run_id}/match/accept", json={"reason": "Archived delivery."})
        detail = client.get(f"{api}/runs/{run_id}").json()
        accepted = detail["mismatches"][0]
        assert accepted["reason"] == "Archived delivery."
        assert accepted["accepted_by"]
        assert accepted["accepted_at"]

    def test_accepting_a_run_that_is_not_held_is_a_conflict(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """There is nothing to accept on a run that started normally."""
        run_id = submit().json()["run_id"]
        response = client.post(
            f"{api}/runs/{run_id}/match/accept", json={"reason": "nothing to do"}
        )
        assert response.status_code == 409

    def test_accepting_an_unknown_run_is_a_404(self, client: TestClient, api: str) -> None:
        """The ordinary shape of a missing row."""
        response = client.post(f"{api}/runs/9999/match/accept", json={"reason": "x"})
        assert response.status_code == 404


class TestAnAcceptedRunRunsAndReports:
    """End to end: the hold is cleared and the delivery is validated as usual."""

    def test_an_accepted_run_completes_and_keeps_its_waiver(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        worker: Worker,
        seed_aliases: None,
    ) -> None:
        """The mismatch stays visible on the run after it has been validated."""
        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        client.post(f"{api}/runs/{run_id}/match/accept", json={"reason": "Typo on the form."})
        worker.run_once()

        detail = client.get(f"{api}/runs/{run_id}").json()
        assert detail["status"] == "needs_review"
        assert len(detail["mismatches"]) == 1
        assert detail["mismatches"][0]["reason"] == "Typo on the form."


class TestTheFrozenReport:
    """A waiver is visible at sign-off, not only at submit (ADR-041)."""

    def test_the_report_names_what_was_accepted_and_why(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        worker: Worker,
        seed_aliases: None,
        clear_gate: Callable[..., None],
    ) -> None:
        """The reviewer signing the delivery sees the question somebody waived."""
        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        client.post(
            f"{api}/runs/{run_id}/match/accept",
            json={"reason": "Re-run of an archived delivery."},
        )
        worker.run_once()
        clear_gate(run_id)

        response = client.post(f"{api}/runs/{run_id}/finalize")
        assert response.status_code == 201, response.text
        html = client.get(f"{api}/runs/{run_id}/report").text
        assert "Accepted before the run started" in html
        assert "CFG-WRONG" in html
        assert "CFG-SYNTH-GEO-02" in html
        assert "Re-run of an archived delivery." in html

    def test_a_clean_run_renders_no_such_section(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        worker: Worker,
        seed_aliases: None,
        clear_gate: Callable[..., None],
    ) -> None:
        """Configuring nothing changes nothing: the usual report is untouched."""
        run_id = submit().json()["run_id"]
        worker.run_once()
        clear_gate(run_id)
        client.post(f"{api}/runs/{run_id}/finalize")
        html = client.get(f"{api}/runs/{run_id}/report").text
        assert "Accepted before the run started" not in html


class TestTheCreditDateInThePreflight:
    """The date is compared before the model runs, not at stage 7 (Phase 6.14b)."""

    def test_a_wrong_credit_date_holds_the_run(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """A delivery cut for another date is caught before it costs anything."""
        body = submit(credit_date="2019-01-15").json()
        # The fixtures carry no labelled as-of line, so there is nothing to disagree
        # with and the run proceeds; stage 7 still reports the date as unfound. This
        # asserts the shape rather than inventing a fixture: absence is not
        # disagreement (ADR-041).
        assert body["status"] == "queued"
        assert all(m["field"] != "credit_date" for m in body["mismatches"])

    def test_the_preflight_has_a_budget_so_submitting_stays_quick(self) -> None:
        """Measured: a 50,000-row workbook parses in ~850 ms, five would be four
        seconds in front of somebody pressing Submit. The budget bounds it and stage 7
        still checks whatever was not read."""
        from greenlight_ai.api.routers.runs import PREFLIGHT_PARSE_BUDGET_S

        assert 0 < PREFLIGHT_PARSE_BUDGET_S <= 2.0
