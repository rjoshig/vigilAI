"""Holding work, stopping it, and taking a submission back (Phase 6.14j).

Four switches with different intents, and the thing worth protecting is that they mean
different things: a held queue accepts work and starts none of it; stopped submissions
refuse work and finish what is already queued; maintenance implies both; and the
change-your-mind window is per run rather than deployment-wide.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.config.store import invalidate
from greenlight_ai.db import models
from greenlight_ai.worker.app import Worker


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    """Keep one test's overrides out of the next test's cache."""
    invalidate()
    yield
    invalidate()


def _set(client: TestClient, api: str, key: str, value: Any) -> None:
    """Set a runtime setting the way the console does."""
    response = client.post(f"{api}/admin/settings", json={"key": key, "value": value})
    assert response.status_code == 200, response.text
    invalidate()


class TestStoppingSubmissions:
    """Refused at the door, before seven files travel."""

    def test_a_submission_is_refused_with_the_message(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """The person is told why, not given a bare error."""
        _set(client, api, "submissions.paused", True)
        _set(client, api, "maintenance.message", "Back at 2am.")

        response = submit()
        assert response.status_code == 503
        assert response.json()["detail"] == "Back at 2am."

    def test_nothing_is_stored_for_a_refused_submission(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
    ) -> None:
        """Refusing after storing would leave orphan files nobody asked for."""
        _set(client, api, "submissions.paused", True)
        submit()
        with factory() as session:
            assert session.query(models.Run).count() == 0

    def test_work_already_queued_still_runs(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        worker: Worker,
        seed_aliases: None,
    ) -> None:
        """Stopping submissions is about new work, not about abandoning the backlog."""
        run_id = submit().json()["run_id"]
        _set(client, api, "submissions.paused", True)

        worker.run_once()
        assert client.get(f"{api}/runs/{run_id}").json()["status"] == "needs_review"


class TestHoldingTheQueue:
    """Accepted, and not started."""

    def test_a_held_queue_accepts_but_starts_nothing(
        self, submit: Callable[..., Any], client: TestClient, api: str, worker: Worker
    ) -> None:
        """The distinction from stopping submissions, in one test."""
        _set(client, api, "queue.paused", True)

        created = submit()
        assert created.status_code == 201
        run_id = created.json()["run_id"]

        assert worker.run_once() is False
        assert client.get(f"{api}/runs/{run_id}").json()["status"] == "queued"

    def test_releasing_the_queue_starts_the_backlog(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        worker: Worker,
        seed_aliases: None,
    ) -> None:
        """What was waiting runs, without anybody resubmitting it."""
        _set(client, api, "queue.paused", True)
        run_id = submit().json()["run_id"]
        assert worker.run_once() is False

        _set(client, api, "queue.paused", False)
        assert worker.run_once() is True
        assert client.get(f"{api}/runs/{run_id}").json()["status"] == "needs_review"


class TestMaintenanceMode:
    """One switch that implies the other two."""

    def test_maintenance_refuses_submissions_and_holds_the_queue(
        self, submit: Callable[..., Any], client: TestClient, api: str, worker: Worker
    ) -> None:
        """A caller asking one question gets the whole answer."""
        run_id = submit().json()["run_id"]
        _set(client, api, "maintenance.mode", True)

        assert submit().status_code == 503
        assert worker.run_once() is False
        assert client.get(f"{api}/runs/{run_id}").json()["status"] == "queued"

    def test_the_console_keeps_working_during_maintenance(
        self, client: TestClient, api: str
    ) -> None:
        """A switch you cannot reach to turn off is a switch that strands you."""
        _set(client, api, "maintenance.mode", True)
        assert client.get(f"{api}/admin/settings").status_code == 200
        _set(client, api, "maintenance.mode", False)
        assert client.get(f"{api}/appearance").json()["maintenance"] is False


class TestCancelling:
    """Taking a submission back before it has cost anything."""

    def test_a_queued_run_can_be_cancelled(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """The wrong file, the wrong order number, a second thought."""
        run_id = submit().json()["run_id"]
        response = client.post(f"{api}/runs/{run_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    def test_a_cancelled_run_never_starts(
        self, submit: Callable[..., Any], client: TestClient, api: str, worker: Worker
    ) -> None:
        """Cancelling has to drop the job, not merely relabel the run."""
        run_id = submit().json()["run_id"]
        client.post(f"{api}/runs/{run_id}/cancel")
        assert worker.run_once() is False
        assert client.get(f"{api}/runs/{run_id}").json()["status"] == "cancelled"

    def test_the_files_are_kept(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        factory: sessionmaker[Session],
    ) -> None:
        """So the next step is cloning it corrected, not finding seven files again."""
        run_id = submit().json()["run_id"]
        client.post(f"{api}/runs/{run_id}/cancel")
        with factory() as session:
            files = session.query(models.RunFile).filter_by(run_id=run_id).count()
        assert files == 7

    def test_a_finished_run_cannot_be_cancelled(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        worker: Worker,
        seed_aliases: None,
    ) -> None:
        """There is nothing to take back, and the conflict says so."""
        run_id = submit().json()["run_id"]
        worker.run_once()
        response = client.post(f"{api}/runs/{run_id}/cancel")
        assert response.status_code == 409
        assert "only a run that has not started" in response.json()["detail"]

    def test_a_held_run_can_be_cancelled(
        self, submit: Callable[..., Any], client: TestClient, api: str
    ) -> None:
        """A mismatch somebody would rather fix on the form than accept."""
        run_id = submit(configuration_id="CFG-WRONG").json()["run_id"]
        assert client.post(f"{api}/runs/{run_id}/cancel").status_code == 200


class TestTheGraceWindow:
    """The window itself, which the rest of the suite switches off."""

    def test_a_run_waits_before_the_worker_may_take_it(
        self,
        submit: Callable[..., Any],
        client: TestClient,
        api: str,
        worker: Worker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Thirty seconds in which cancelling costs nothing."""
        monkeypatch.setenv("GREENLIGHT_AI_QUEUE_GRACE_S", "120")
        invalidate()

        run_id = submit().json()["run_id"]
        assert worker.run_once() is False
        assert client.get(f"{api}/runs/{run_id}").json()["status"] == "queued"

    def test_zero_starts_at_once(
        self,
        submit: Callable[..., Any],
        worker: Worker,
        seed_aliases: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An administrator who wants no window can have none."""
        monkeypatch.setenv("GREENLIGHT_AI_QUEUE_GRACE_S", "0")
        invalidate()

        submit()
        assert worker.run_once() is True
