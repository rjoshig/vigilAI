"""Two settings the console offered and nothing read (Phase 6.23d).

`retention.days` and `uploads.max_mb` were both editable in the admin console and both
dead: `expiry_from`'s ``days`` was never passed and `store_upload`'s ``max_bytes`` never
came from the resolver. A setting a console offers and nothing reads is worse than no
setting — somebody changes it, watches nothing happen, and stops trusting the screen.

These assert the windows and the limit **by measuring what changing them does**, not by
grepping for a call, because a call is a claim and a date is a fact. They also pin the
one rule that makes a retention promise keepable: a run is stamped once, so lowering the
window later never shortens the life of something that already exists (ADR-065).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
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


def _set(client: TestClient, api: str, key: str, value: object) -> None:
    response = client.post(f"{api}/admin/settings", json={"key": key, "value": value})
    assert response.status_code == 200, response.text


def _days_until(stamp: str, created: str) -> float:
    """How many whole days apart two API timestamps are.

    The ``Z`` suffix is spelled out because `fromisoformat` only learned to read it in
    Python 3.11, and ADR-010 pins 3.10 as the floor: without this the helper raises
    `ValueError` on the interpreter the project actually targets, and the assertion
    below never runs.
    """

    def read(value: str) -> dt.datetime:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))

    return (read(stamp) - read(created)).days


class TestTheWindowsAreRead:
    """Change the number, and the date moves."""

    def test_a_run_uses_the_configured_retention(
        self, client: TestClient, api: str, submit: Submit
    ) -> None:
        _set(client, api, "retention.days", 7)
        run = client.get(f"{api}/runs/{submit().json()['run_id']}").json()
        assert _days_until(run["expires_at"], run["created_at"]) == 7

    def test_a_draft_uses_the_configured_draft_window(
        self, client: TestClient, api: str, submit: Submit
    ) -> None:
        _set(client, api, "retention.draft_days", 2)
        run_id = submit().json()["run_id"]
        draft_id = client.post(f"{api}/runs/{run_id}/clone").json()["run_id"]
        draft = client.get(f"{api}/runs/{draft_id}").json()
        assert _days_until(draft["expires_at"], draft["created_at"]) == 2

    def test_the_default_draft_window_is_five_days(
        self, client: TestClient, api: str, submit: Submit
    ) -> None:
        """The number the phase was specified around, with nothing configured."""
        run_id = submit().json()["run_id"]
        draft_id = client.post(f"{api}/runs/{run_id}/clone").json()["run_id"]
        draft = client.get(f"{api}/runs/{draft_id}").json()
        assert _days_until(draft["expires_at"], draft["created_at"]) == 5

    def test_lowering_the_window_does_not_shorten_what_already_exists(
        self, client: TestClient, api: str, submit: Submit
    ) -> None:
        """The promise the setting's own help text makes (ADR-065)."""
        run = client.get(f"{api}/runs/{submit().json()['run_id']}").json()
        before = run["expires_at"]
        _set(client, api, "retention.days", 1)
        assert client.get(f"{api}/runs/{run['id']}").json()["expires_at"] == before


class TestTheUploadLimitIsRead:
    """The other setting that was offered and ignored."""

    def test_a_file_over_the_configured_limit_is_refused(
        self, client: TestClient, api: str, fixtures_root: Path, cases: dict[str, Any]
    ) -> None:
        _set(client, api, "uploads.max_mb", 1)
        case = cases["baseline_match"]
        oversized = b"x" * (2 * 1024 * 1024)
        response = client.post(
            f"{api}/runs",
            data={
                "customer_name": case["customer"],
                "order_number": "OVERSIZED-1",
                "configuration_id": case["configuration_id"],
            },
            files=[
                ("osl", ("osl.docx", oversized, "application/octet-stream")),
                (
                    "config",
                    (
                        "config.json",
                        (fixtures_root / case["config"]).read_bytes(),
                        "application/json",
                    ),
                ),
                *[
                    (
                        kind,
                        (
                            f"{kind}.xlsx",
                            (fixtures_root / path).read_bytes(),
                            "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet",
                        ),
                    )
                    for kind, path in case["reports"].items()
                ],
            ],
        )
        assert response.status_code == 400
        assert "1 MB limit" in response.json()["detail"]


class TestThePurgeActsOnIt:
    """A window nothing enforces is a promise, not a retention policy."""

    def test_an_expired_draft_is_deleted(
        self,
        client: TestClient,
        api: str,
        submit: Submit,
        factory: sessionmaker[Session],
        worker: Any,
    ) -> None:
        run_id = submit().json()["run_id"]
        draft_id = client.post(f"{api}/runs/{run_id}/clone").json()["run_id"]

        with factory() as session:
            draft = session.get(models.Run, draft_id)
            assert draft is not None
            draft.expires_at = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
            session.commit()

        # The submitted run's own pipeline job is ahead of the purge in the queue.
        worker.ensure_purge_scheduled()
        while worker.run_once():
            pass

        assert client.get(f"{api}/runs/{draft_id}").status_code == 404
        # And the run it was cloned from is untouched, because its own window is open.
        assert client.get(f"{api}/runs/{run_id}").status_code == 200
