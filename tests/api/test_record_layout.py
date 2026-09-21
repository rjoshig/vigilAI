"""The record layout end to end: upload, run, promote, borrow (Phase 6.22b).

Driven through the real multipart endpoint and the real worker, because the three ways
this goes wrong are all at the seams: an optional slot that turns out not to be
optional, a snapshot written for the wrong run, and a borrowed layout that does not say
it was borrowed.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models, record_layouts
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]

CASE = "record_layout_supplied"


def _run_to_review(submit: Submit, worker: Worker, case: str = CASE, **extra: str) -> int:
    """Submit a case and drive the worker until the run needs review."""
    run_id = int(submit(case, **extra).json()["run_id"])
    worker.run_once()
    return run_id


class TestTheUploadSlot:
    """It appears, and it is optional."""

    def test_the_new_run_form_offers_a_record_layout_slot(
        self, client: TestClient, api: str
    ) -> None:
        options = client.get(f"{api}/runs/options").json()
        slot = next(a for a in options["artifacts"] if a["key"] == "record_layout")
        assert slot["kind"] == "record_layout"
        assert slot["is_required"] is False
        assert slot["accept"] == ".xlsx"

    def test_a_delivery_that_uploads_none_still_runs(
        self, submit: Submit, worker: Worker, factory: sessionmaker[Session]
    ) -> None:
        """The ordinary case, and the one that must not change.

        ``baseline_match`` ships no record layout, so this is the whole product as it
        behaved before the slot existed.
        """
        run_id = _run_to_review(submit, worker, "baseline_match")
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert run.status == "needs_review"
            assert run.record_layout == []

    def test_an_uploaded_layout_is_stored_as_a_file_of_its_own_kind(
        self, submit: Submit, factory: sessionmaker[Session]
    ) -> None:
        run_id = int(submit(CASE).json()["run_id"])
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert {f.kind for f in run.files} >= {"osl", "config", "record_layout", "dirt"}


class TestWhatTheRunKeeps:
    """Stage 1 reads it; the run keeps a snapshot of what it was checked against."""

    def test_the_run_snapshots_the_layout_it_was_checked_against(
        self, submit: Submit, worker: Worker, factory: sessionmaker[Session]
    ) -> None:
        run_id = _run_to_review(submit, worker)
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            names = [f["name"] for f in run.record_layout]
            assert "SCORE_V3" in names
            # The two fields the OSL never asked for are in the layout as delivered.
            assert "INTERNAL_SEQ" in names
            # It uploaded its own, so nothing is borrowed.
            assert run.record_layout_run_id == 0

    def test_the_layout_is_not_parsed_as_a_report(
        self, submit: Submit, worker: Worker, factory: sessionmaker[Session]
    ) -> None:
        """It is a schema, not a workbook of results.

        Reading it as a report would put a phantom report type into coverage and have
        every cross-report check look for values in it.
        """
        run_id = _run_to_review(submit, worker)
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert "record_layout" not in {row["kind"] for row in (run.report_coverage or [])}


class TestPromotingAndBorrowing:
    """Finalize promotes; the next delivery of the same order borrows."""

    def test_finalizing_promotes_the_layout_onto_the_configuration(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        clear_gate: Callable[..., None],
        factory: sessionmaker[Session],
    ) -> None:
        run_id = _run_to_review(submit, worker)
        clear_gate(run_id)
        assert client.post(f"{api}/runs/{run_id}/finalize").status_code in (200, 201)

        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            row = record_layouts.promoted_for(session, run.customer_name, run.configuration_id)
            assert row is not None
            assert row.source_run_id == run_id
            assert row.source_filename == "record_layout.xlsx"

    def test_a_run_that_is_only_reviewed_promotes_nothing(
        self, submit: Submit, worker: Worker, factory: sessionmaker[Session]
    ) -> None:
        """A layout nobody has signed off is not yet this configuration's shape."""
        run_id = _run_to_review(submit, worker)
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            assert record_layouts.promoted_for(session, run.customer_name, CASE) is None

    def test_the_next_delivery_that_uploads_none_borrows_it_and_says_which_run(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        clear_gate: Callable[..., None],
        factory: sessionmaker[Session],
        fixtures_root: Any,
        cases: dict[str, Any],
    ) -> None:
        first = _run_to_review(submit, worker)
        clear_gate(first)
        client.post(f"{api}/runs/{first}/finalize")

        # The same order again, with every file except the record layout.
        case = cases[CASE]
        files = [
            (
                "osl",
                (
                    "osl.docx",
                    (fixtures_root / case["osl"]).read_bytes(),
                    "application/octet-stream",
                ),
            ),
            (
                "config",
                ("config.json", (fixtures_root / case["config"]).read_bytes(), "application/json"),
            ),
        ]
        for kind, path in case["reports"].items():
            files.append(
                (
                    kind,
                    (
                        f"{kind}.xlsx",
                        (fixtures_root / path).read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )
            )
        second = int(
            client.post(
                f"{api}/runs",
                data={
                    "customer_name": case["customer"],
                    "order_number": case["order_number"],
                    "configuration_id": case["configuration_id"],
                    "rerun_reason": "the same order next month, without the layout",
                },
                files=files,
            ).json()["run_id"]
        )
        worker.run_once()

        with factory() as session:
            run = session.get(models.Run, second)
            assert run is not None
            assert run.record_layout_run_id == first
            assert run.record_layout_source_date
            borrowed = record_layouts.load_for_run(session, run)
            assert borrowed.borrowed
            assert borrowed.provenance.startswith(f"from run {first} finalized ")
            assert "SCORE_V3" in borrowed.names
