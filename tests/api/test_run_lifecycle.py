"""What a run's state is allowed to permit (Phase 6.23a).

Three routes refuse a finalized run because freezing a report means freezing what the
reviewer was shown (hard rule 5, ADR-005). `POST /runs/{id}/recheck` did not, and a
re-check rewrites rules, traces and findings — so a frozen report could come to describe
a run that no longer existed underneath it.

The same guard answers every other wrong state at once, which is why these tests are one
file rather than one per defect: a draft with no files, a queued or running job the
pipeline owns, a failed or cancelled run with nothing to re-compare.
"""

from __future__ import annotations

from typing import Any, Callable

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models

Submit = Callable[..., Any]


def _set_status(factory: sessionmaker[Session], run_id: int, status: str) -> None:
    """Put a run into a state the API cannot reach directly."""
    with factory() as session:
        run = session.get(models.Run, run_id)
        assert run is not None
        run.status = status
        session.commit()


# --- a re-check belongs to review, and only to review ---------------------------------


def test_a_finalized_run_cannot_be_rechecked(
    client: TestClient, api: str, submit: Submit, factory: sessionmaker[Session]
) -> None:
    """The hole in the freeze invariant.

    Re-reviewing a finalized run is already refused by the findings, coverage and report
    routes. A re-check rewrites the same rows those routes protect, and it was accepted.
    """
    run_id = submit().json()["run_id"]
    _set_status(factory, run_id, "finalized")

    response = client.post(f"{api}/runs/{run_id}/recheck")
    assert response.status_code == 409
    assert "finalized" in response.json()["detail"]


def test_a_draft_cannot_be_rechecked(
    client: TestClient, api: str, submit: Submit, factory: sessionmaker[Session]
) -> None:
    """A draft has no files, so a re-check would parse nothing and report on it."""
    run_id = submit().json()["run_id"]
    _set_status(factory, run_id, "draft")

    assert client.post(f"{api}/runs/{run_id}/recheck").status_code == 409


def test_a_queued_run_cannot_be_rechecked(client: TestClient, api: str, submit: Submit) -> None:
    """The pipeline owns the row while it is queued; two writers is the race."""
    run_id = submit().json()["run_id"]
    assert client.post(f"{api}/runs/{run_id}/recheck").status_code == 409


def test_a_run_awaiting_review_can_be_rechecked(
    client: TestClient, api: str, submit: Submit, worker: Any
) -> None:
    """The one case the guard must let through, or the feature is gone."""
    run_id = submit().json()["run_id"]
    worker.run_once()

    response = client.post(f"{api}/runs/{run_id}/recheck")
    assert response.status_code == 200
    assert response.json()["queued"] is True


def test_editing_requirements_is_refused_once_the_report_is_frozen(
    client: TestClient, api: str, submit: Submit, worker: Any, factory: sessionmaker[Session]
) -> None:
    """The edit path queues a re-check of its own, so it needs the same guard."""
    run_id = submit().json()["run_id"]
    worker.run_once()
    _set_status(factory, run_id, "finalized")

    rules = client.get(f"{api}/runs/{run_id}/requirements").json()
    rule_id = rules["rules"][0]["rule_id"]
    response = client.put(
        f"{api}/runs/{run_id}/requirements",
        json={"edits": [{"rule_id": rule_id, "reason": "correcting the threshold"}]},
    )
    assert response.status_code == 409


# --- the gate answers for the whole run, not only for its findings --------------------


def test_a_draft_cannot_be_finalized_and_says_why(
    client: TestClient, api: str, submit: Submit, factory: sessionmaker[Session]
) -> None:
    """The gate used to call an empty draft ready to freeze.

    It counted undecided findings, unacknowledged requirements and second approvals —
    and a draft has none of any, so every test passed vacuously and the screen offered
    a button whose tooltip said every high-severity finding had a decision.
    """
    run_id = submit().json()["run_id"]
    _set_status(factory, run_id, "draft")

    body = client.get(f"{api}/runs/{run_id}").json()
    assert body["can_finalize"] is False
    assert body["finalize_blocked_by"]
    assert "draft" in body["finalize_blocked_by"]


def test_a_run_awaiting_review_still_reports_its_real_blockers(
    client: TestClient, api: str, submit: Submit, worker: Any
) -> None:
    """The new condition must not mask the reasons the gate already gave."""
    run_id = submit().json()["run_id"]
    worker.run_once()

    body = client.get(f"{api}/runs/{run_id}").json()
    if not body["can_finalize"]:
        assert "decision" in body["finalize_blocked_by"] or "acknowledged" in (
            body["finalize_blocked_by"]
        )


# --- the audit records what happened, not what happens next ---------------------------


def test_cancelling_audits_the_status_the_run_actually_had(
    client: TestClient, api: str, submit: Submit, factory: sessionmaker[Session]
) -> None:
    """The detail read ``run.status`` after setting it, so every entry said the same.

    An audit line that always says "was cancelled" records nothing at all: the one fact
    it exists to keep is what the run was before somebody stopped it.
    """
    run_id = submit().json()["run_id"]
    assert client.post(f"{api}/runs/{run_id}/cancel").status_code == 200

    with factory() as session:
        detail = session.execute(
            sa.select(models.AuditLog.detail).where(
                models.AuditLog.action == "run.cancelled",
                models.AuditLog.run_id == run_id,
            )
        ).scalar_one()
    assert detail == "was queued"


# --- the status vocabulary is one set, in two languages -------------------------------


def test_the_status_set_matches_the_one_the_browser_knows() -> None:
    """Two lists of statuses is how a screen comes to render a state it cannot name.

    `user-ui` renders a badge tone and a label per status. A status added in Python and
    not there shows as an unstyled unknown; one there and not in Python is dead code
    nobody notices.
    """
    from pathlib import Path
    import re

    source = Path("user-ui/lib/types.ts").read_text(encoding="utf-8")
    match = re.search(r"export type RunStatus\s*=\s*(.*?);", source, re.S)
    assert match is not None, "RunStatus is no longer declared where this test looks"
    in_browser = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert in_browser == set(models.RUN_STATUSES)
