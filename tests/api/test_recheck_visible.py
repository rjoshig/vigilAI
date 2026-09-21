"""A re-check that can be seen happening (Phase 6.23b).

The standalone Re-check button is gone, and what replaces it is not a second button. A
re-check rebuilds findings and leaves the run in ``needs_review``, so nothing about the
run changes shape while it runs: the screen was byte-identical and the rebuilt findings
appeared only when somebody reloaded by hand. The queue is asked instead.

Three things are pinned here, and the third is the one that mattered most in practice:

1. ``RunDetail.rechecking`` is true while a re-check job is queued or claimed, and false
   before and after — so a screen can poll on it and reload when it clears.
2. Editing a trace link queues that re-check itself. `design.md` has promised this since
   Phase 2 and no screen ever offered it, so the endpoint had no caller at all.
3. **A failed re-check leaves the run reviewable.** It rebuilds findings from rules and
   traces that are already stored, so a run awaiting review still holds every finding it
   had when the job was claimed. Marking it ``failed`` took a reviewable run away from
   the person reviewing it, and no retry gave it back.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.db.queue import JobQueue
from greenlight_ai.worker.app import TASK_RECHECK, Worker

Submit = Callable[..., Any]


def _no_retries(factory: sessionmaker[Session], run_id: int) -> None:
    """Make the next failure fatal, so the test reads the dead-job path rather than
    the backoff that would otherwise hold the retry for ten seconds."""
    with factory() as session:
        job = (
            session.query(models.Job)
            .filter(models.Job.run_id == run_id, models.Job.task == TASK_RECHECK)
            .one()
        )
        job.max_attempts = 1
        session.commit()


def _reviewable(submit: Submit, worker: Worker) -> int:
    """A finished run awaiting review, which is the only state a re-check is allowed in."""
    run_id = int(submit().json()["run_id"])
    worker.run_once()
    return run_id


class TestTheRunSaysItIsHappening:
    """What the screen polls on."""

    def test_a_settled_run_is_not_rechecking(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        run_id = _reviewable(submit, worker)
        assert client.get(f"{api}/runs/{run_id}").json()["rechecking"] is False

    def test_a_queued_recheck_is_visible_before_the_worker_takes_it(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        """Queued counts: the person clicked, and something is going to happen."""
        run_id = _reviewable(submit, worker)
        assert client.post(f"{api}/runs/{run_id}/recheck").status_code == 200
        assert client.get(f"{api}/runs/{run_id}").json()["rechecking"] is True

    def test_it_clears_once_the_recheck_has_run(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        """Which is the edge the screen reloads its findings on."""
        run_id = _reviewable(submit, worker)
        client.post(f"{api}/runs/{run_id}/recheck")
        worker.run_once()
        assert client.get(f"{api}/runs/{run_id}").json()["rechecking"] is False

    def test_another_run_is_unaffected(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        """The queue is asked about one run, not about whether it is busy."""
        first = _reviewable(submit, worker)
        second = int(submit(rerun_reason="the same order again").json()["run_id"])
        worker.run_once()
        client.post(f"{api}/runs/{first}/recheck")
        assert client.get(f"{api}/runs/{second}").json()["rechecking"] is False


class TestTheEditThatQueuesIt:
    """The path every document describes and no screen offered."""

    def test_correcting_a_link_queues_the_recheck_itself(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        run_id = _reviewable(submit, worker)
        requirements = client.get(f"{api}/runs/{run_id}/requirements").json()
        rule_id = requirements["rules"][0]["rule_id"]

        response = client.put(
            f"{api}/runs/{run_id}/requirements",
            json={"edits": [{"rule_id": rule_id, "clear_link": True, "reason": "Not related."}]},
        )
        assert response.status_code == 200
        assert response.json()["queued"] is True
        assert client.get(f"{api}/runs/{run_id}").json()["rechecking"] is True

    def test_the_correction_survives_the_recheck(
        self, submit: Submit, worker: Worker, client: TestClient, api: str
    ) -> None:
        """Because a correction the re-check undid would be worse than no correction."""
        run_id = _reviewable(submit, worker)
        requirements = client.get(f"{api}/runs/{run_id}/requirements").json()
        linked = next(
            (t for t in requirements["traces"] if t["element_id"]),
            None,
        )
        assert linked is not None, "the fixture should trace at least one requirement"

        client.put(
            f"{api}/runs/{run_id}/requirements",
            json={
                "edits": [
                    {
                        "rule_id": linked["rule_id"],
                        "clear_link": True,
                        "reason": "The configuration does not implement this.",
                    }
                ]
            },
        )
        worker.run_once()

        after = client.get(f"{api}/runs/{run_id}/requirements").json()
        corrected = next(t for t in after["traces"] if t["rule_id"] == linked["rule_id"])
        assert corrected["element_id"] is None
        assert corrected["verdict"] == "not_related"

    def test_a_finalized_run_cannot_have_its_links_corrected(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
    ) -> None:
        """The same guard as the re-check, because this is the re-check (ADR-066)."""
        run_id = _reviewable(submit, worker)
        with factory() as session:
            run = session.get(models.Run, run_id)
            assert run is not None
            run.status = "finalized"
            session.commit()

        response = client.put(
            f"{api}/runs/{run_id}/requirements",
            json={"edits": [{"rule_id": "R-001", "clear_link": True, "reason": "x"}]},
        )
        assert response.status_code == 409


class TestAFailedRecheckKeepsTheRun:
    """The defect the visibility work uncovered."""

    def test_the_run_still_awaits_review(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A re-check reads stored rows and writes findings; failing loses neither."""
        run_id = _reviewable(submit, worker)
        before = client.get(f"{api}/runs/{run_id}/findings").json()
        assert before

        import greenlight_ai.worker.app as worker_app

        def _boom(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError("the re-check fell over")

        monkeypatch.setattr(worker_app, "recheck_run", _boom)
        client.post(f"{api}/runs/{run_id}/recheck")
        _no_retries(factory, run_id)
        worker.run_once()

        run = client.get(f"{api}/runs/{run_id}").json()
        assert run["status"] == "needs_review"
        assert "fell over" in run["error"]
        assert len(client.get(f"{api}/runs/{run_id}/findings").json()) == len(before)

    def test_the_job_itself_is_still_marked_failed(
        self,
        submit: Submit,
        worker: Worker,
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Leaving the run alone is not the same as pretending the job succeeded."""
        run_id = _reviewable(submit, worker)
        import greenlight_ai.worker.app as worker_app

        def _boom(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError("the re-check fell over")

        monkeypatch.setattr(worker_app, "recheck_run", _boom)
        client.post(f"{api}/runs/{run_id}/recheck")
        _no_retries(factory, run_id)
        worker.run_once()

        with factory() as session:
            job = (
                session.query(models.Job)
                .filter(models.Job.run_id == run_id, models.Job.task == TASK_RECHECK)
                .one()
            )
            assert job.status == "failed"
            # And nothing is left claiming to be in flight.
            assert JobQueue(session, True).pending_for(run_id, TASK_RECHECK) is False
