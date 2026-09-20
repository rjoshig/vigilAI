"""Coverage on the wire and the fail-closed finalize gate (Phase 6.11c, 6.11d, ADR-035).

The gate used to ask one question: has every high-severity finding been decided? These
prove the three it asks now, and that each one is refused by the API rather than only
greyed out in the screen.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi.testclient import TestClient

from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]


def _completed(submit: Submit, worker: Worker, case: str = "geography_extra_state") -> int:
    """Submit a fixture case and run it to review."""
    run_id = int(submit(case).json()["run_id"])
    worker.run_once()
    return run_id


# --- what coverage says -----------------------------------------------------------------


def test_coverage_reports_a_state_and_a_reason_for_every_requirement(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    run_id = _completed(submit, worker)

    body = client.get(f"{api}/runs/{run_id}/coverage").json()

    assert body["requirements"], "the fixture extracts requirements"
    assert sum(body["counts"].values()) == len(body["requirements"])
    for entry in body["requirements"]:
        assert entry["state"] in {"checked", "traced_unchecked", "untraced", "manual"}
        assert entry["reason"], "every state says why"


def test_coverage_names_the_checks_that_could_not_be_evaluated(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    """Every fixture case carries some, and they are never a silent pass."""
    run_id = _completed(submit, worker, "baseline_match")

    body = client.get(f"{api}/runs/{run_id}/coverage").json()

    assert body["unevaluated"], "the clean baseline still has checks it could not run"
    assert all(not entry["acknowledged"] for entry in body["unevaluated"])


def test_a_report_no_check_examined_is_counted_not_hidden(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    run_id = _completed(submit, worker)

    reports = client.get(f"{api}/runs/{run_id}/coverage").json()["reports"]

    assert reports, "the uploaded reports are listed"
    assert all("checks_applied" in entry for entry in reports)


def test_coverage_for_an_unknown_run_is_a_404(client: TestClient, api: str) -> None:
    assert client.get(f"{api}/runs/9999/coverage").status_code == 404


# --- the gate ---------------------------------------------------------------------------


def test_an_unacknowledged_gap_blocks_finalizing(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    """The hole this phase closes: nothing said these were never checked."""
    run_id = _completed(submit, worker)
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "false_positive", "review_note": "checked"},
        )

    detail = client.get(f"{api}/runs/{run_id}").json()
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]

    assert outstanding, "this fixture leaves something unchecked"
    assert detail["can_finalize"] is False
    assert "acknowledged" in detail["finalize_blocked_by"]
    refused = client.post(f"{api}/runs/{run_id}/finalize")
    assert refused.status_code == 409
    assert "cannot be finalized yet" in refused.json()["detail"]


def test_acknowledging_every_gap_opens_the_gate(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    run_id = _completed(submit, worker)
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "false_positive", "review_note": "checked"},
        )
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]

    written = client.post(
        f"{api}/runs/{run_id}/coverage/acknowledge",
        json={"targets": outstanding, "note": "raised with the delivery lead"},
    )

    assert written.status_code == 200
    assert written.json() == len(outstanding)
    detail = client.get(f"{api}/runs/{run_id}").json()
    assert detail["can_finalize"] is True
    assert detail["finalize_blocked_by"] == ""


def test_an_acknowledgement_names_who_made_it(
    submit: Submit, worker: Worker, client: TestClient, api: str, clear_gate: Callable[..., None]
) -> None:
    run_id = _completed(submit, worker)
    clear_gate(run_id, note="seen and accepted")

    body = client.get(f"{api}/runs/{run_id}/coverage").json()
    acknowledged = [e for e in body["requirements"] if e["acknowledged"]]

    assert acknowledged, "the fixture leaves something to acknowledge"
    assert all(e["acknowledged_by"] for e in acknowledged)
    assert all(e["acknowledgement_note"] == "seen and accepted" for e in acknowledged)


def test_acknowledging_something_that_is_not_a_gap_is_refused(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    """An acknowledgement that names nothing would satisfy the gate covering nothing."""
    run_id = _completed(submit, worker)

    response = client.post(
        f"{api}/runs/{run_id}/coverage/acknowledge",
        json={"targets": ["R-does-not-exist"], "note": ""},
    )

    assert response.status_code == 422
    assert "nothing on this run needs acknowledging" in response.json()["detail"]


def test_acknowledging_twice_writes_one_row(
    submit: Submit, worker: Worker, client: TestClient, api: str
) -> None:
    run_id = _completed(submit, worker)
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]

    first = client.post(f"{api}/runs/{run_id}/coverage/acknowledge", json={"targets": outstanding})
    second = client.post(f"{api}/runs/{run_id}/coverage/acknowledge", json={"targets": outstanding})

    assert first.json() == len(outstanding)
    assert second.json() == 0


def test_acknowledging_a_frozen_run_is_refused(
    submit: Submit, worker: Worker, client: TestClient, api: str, clear_gate: Callable[..., None]
) -> None:
    run_id = _completed(submit, worker)
    clear_gate(run_id)
    client.post(f"{api}/runs/{run_id}/finalize")

    response = client.post(f"{api}/runs/{run_id}/coverage/acknowledge", json={"targets": ["R-1"]})

    assert response.status_code == 409


# --- the attestation --------------------------------------------------------------------


def test_the_frozen_report_carries_what_was_checked(
    submit: Submit, worker: Worker, client: TestClient, api: str, clear_gate: Callable[..., None]
) -> None:
    run_id = _completed(submit, worker)
    clear_gate(run_id)
    client.post(f"{api}/runs/{run_id}/finalize")

    html = client.get(f"{api}/runs/{run_id}/report").text

    assert "What was checked" in html
    assert "Checked against a report" in html
    assert "absence of a finding is not on its own a pass" in html


def test_the_attestation_is_stored_with_the_report(
    submit: Submit,
    worker: Worker,
    client: TestClient,
    api: str,
    clear_gate: Callable[..., None],
    factory,
) -> None:
    """A report that is evidence of a review should say what the reviewer was shown."""
    from greenlight_ai.db import models

    run_id = _completed(submit, worker)
    clear_gate(run_id)
    client.post(f"{api}/runs/{run_id}/finalize")

    with factory() as session:
        stored = session.query(models.FinalReport).filter_by(run_id=run_id).one()
        attestation = dict(stored.attestation or {})

    assert set(attestation["coverage"]) == {"checked", "traced_unchecked", "untraced", "manual"}
    assert attestation["requirements_total"] == sum(attestation["coverage"].values())
    assert "unevaluated_checks" in attestation
    assert "definition_versions" in attestation


def test_a_run_from_before_coverage_existed_still_finalizes(
    submit: Submit, worker: Worker, client: TestClient, api: str, factory
) -> None:
    """An empty coverage column reads as nothing to acknowledge, not as a blocker."""
    from greenlight_ai.db import models

    run_id = _completed(submit, worker)
    with factory() as session:
        run = session.get(models.Run, run_id)
        run.coverage = []
        run.report_coverage = []
        session.commit()

    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "false_positive", "review_note": "checked"},
        )
    # Only the unevaluated checks remain, which are findings and exist either way.
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]
    if outstanding:
        client.post(f"{api}/runs/{run_id}/coverage/acknowledge", json={"targets": outstanding})

    assert client.post(f"{api}/runs/{run_id}/finalize").status_code == 201
