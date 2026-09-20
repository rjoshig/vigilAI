"""Four eyes on what one reviewer waved through (ADR-036).

A programme decides in advance that some findings are not one person's call. The rule
is off by default, it is inert while login is off, and it is deliberately narrow: it
asks for a signature from someone other than the reviewer, and nothing else.

Login is on in most of these, because that is the only state in which the control
exists. With it off every action belongs to the same placeholder account, so a second
approver would be the same person and no affected run could ever be frozen — which is
why the rule stands down rather than deadlocking, and why that has a test of its own.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.api.app import create_app
from greenlight_ai.auth.accounts import BOOTSTRAP_PASSWORD, BOOTSTRAP_USERNAME
from greenlight_ai.auth.settings import AuthSettings
from greenlight_ai.db import models
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.worker.app import Worker

Submit = Callable[..., Any]

#: Long enough for the only password rule there is.
PASSWORD = "a-long-enough-password"
SECOND = "another-long-password"


@pytest.fixture()
def programme_asking(factory: sessionmaker[Session]) -> str:
    """A delivery programme that asks for a second approver."""
    from greenlight_ai.db import catalog

    with factory() as session:
        catalog.seed_defaults(session)
        scope = session.query(models.RunScope).first()
        assert scope is not None
        scope.second_approver = True
        code = scope.code
        session.commit()
    return code


@pytest.fixture()
def signed_in(
    db_settings: DbSettings, factory: sessionmaker[Session], programme_asking: str
) -> Iterator[TestClient]:
    """A client with login on, signed in as the reviewer, with a second account ready."""
    app = create_app(db_settings, auth_settings=AuthSettings(admin_auth=True, user_auth=True))
    app.state.session_factory = factory
    with TestClient(app) as client:
        prefix = "/api/v1"
        changed = client.post(
            f"{prefix}/auth/change-password",
            json={
                "username": BOOTSTRAP_USERNAME,
                "current_password": BOOTSTRAP_PASSWORD,
                "new_password": PASSWORD,
            },
        )
        assert changed.status_code == 200, changed.text

        made = client.post(
            f"{prefix}/admin/users",
            json={
                "username": "second",
                "name": "Second Pair Of Eyes",
                "email": "second@example.com",
                "password": SECOND,
                "role": "user",
            },
        )
        assert made.status_code == 201, made.text
        yield client


def _sign_in(client: TestClient, api: str, username: str, password: str) -> None:
    """Sign in, changing the password first when the account still must."""
    login = client.post(f"{api}/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    if login.json().get("must_change_password"):
        changed = client.post(
            f"{api}/auth/change-password",
            json={
                "username": username,
                "current_password": password,
                "new_password": f"{password}-x",
            },
        )
        assert changed.status_code == 200, changed.text


def _completed(submit: Submit, worker: Worker, programme: str) -> int:
    """A run in that programme, executed to review."""
    run_id = int(submit("rule_missing_in_config", scope=programme).json()["run_id"])
    worker.run_once()
    return run_id


def _wave_through(client: TestClient, api: str, run_id: int) -> list[str]:
    """Mark every finding OK, as a reviewer might. Returns the serious ones."""
    waved: list[str] = []
    for finding in client.get(f"{api}/runs/{run_id}/findings").json():
        client.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "false_positive", "review_note": "checked"},
        )
        if finding["type"] in ("programme_rule_violation", "rule_missing_in_config"):
            waved.append(finding["finding_id"])
    return waved


def _acknowledge(client: TestClient, api: str, run_id: int) -> None:
    """Clear the coverage half of the gate."""
    outstanding = client.get(f"{api}/runs/{run_id}/coverage").json()["outstanding"]
    if outstanding:
        client.post(f"{api}/runs/{run_id}/coverage/acknowledge", json={"targets": outstanding})


# --- off by default ----------------------------------------------------------------------


def test_a_programme_that_does_not_ask_needs_no_second_approval(
    submit: Submit, worker: Worker, client: TestClient, api: str, clear_gate: Callable[..., None]
) -> None:
    """Every programme is like this until an administrator says otherwise."""
    run_id = int(submit("rule_missing_in_config").json()["run_id"])
    worker.run_once()
    clear_gate(run_id)

    body = client.get(f"{api}/runs/{run_id}/second-approval").json()

    assert body["required"] is False
    assert body["outstanding"] is False
    assert client.get(f"{api}/runs/{run_id}").json()["can_finalize"] is True


def test_with_login_off_the_switch_stands_down_rather_than_deadlocking(
    submit: Submit,
    worker: Worker,
    client: TestClient,
    api: str,
    programme_asking: str,
    clear_gate: Callable[..., None],
) -> None:
    """A gate nobody can pass is worse than no gate (ADR-022, ADR-036)."""
    run_id = _completed(submit, worker, programme_asking)
    _wave_through(client, api, run_id)
    clear_gate(run_id)

    detail = client.get(f"{api}/runs/{run_id}").json()

    assert detail["can_finalize"] is True, detail["finalize_blocked_by"]
    assert client.post(f"{api}/runs/{run_id}/finalize").status_code == 201


# --- when it does ask ---------------------------------------------------------------------


def test_waving_a_serious_finding_through_holds_the_gate(
    signed_in: TestClient, api: str, submit: Submit, worker: Worker, programme_asking: str
) -> None:
    run_id = _completed(submit, worker, programme_asking)
    waved = _wave_through(signed_in, api, run_id)
    assert waved, "this fixture raises a finding the programme treats as serious"
    _acknowledge(signed_in, api, run_id)

    detail = signed_in.get(f"{api}/runs/{run_id}").json()

    assert detail["can_finalize"] is False
    assert "second person" in detail["finalize_blocked_by"]
    refused = signed_in.post(f"{api}/runs/{run_id}/finalize")
    assert refused.status_code == 409


def test_a_second_person_opens_the_gate(
    signed_in: TestClient, api: str, submit: Submit, worker: Worker, programme_asking: str
) -> None:
    run_id = _completed(submit, worker, programme_asking)
    _wave_through(signed_in, api, run_id)
    _acknowledge(signed_in, api, run_id)

    _sign_in(signed_in, api, "second", SECOND)
    approved = signed_in.post(
        f"{api}/runs/{run_id}/second-approval",
        json={"note": "agreed with the delivery lead"},
    )

    assert approved.status_code == 200, approved.text
    assert approved.json()["outstanding"] is False
    assert approved.json()["approved_by"] == "Second Pair Of Eyes"
    assert signed_in.get(f"{api}/runs/{run_id}").json()["can_finalize"] is True


def test_the_reviewer_cannot_be_their_own_second_approver(
    signed_in: TestClient, api: str, submit: Submit, worker: Worker, programme_asking: str
) -> None:
    """The whole of what this control asserts is a different pair of eyes."""
    run_id = _completed(submit, worker, programme_asking)
    _wave_through(signed_in, api, run_id)
    _acknowledge(signed_in, api, run_id)

    refused = signed_in.post(f"{api}/runs/{run_id}/second-approval", json={})

    assert refused.status_code == 422
    assert "someone other than the reviewer" in refused.json()["detail"]


def test_deciding_everything_not_ok_needs_no_second_approval(
    signed_in: TestClient, api: str, submit: Submit, worker: Worker, programme_asking: str
) -> None:
    """The rule is about what was waved through, not about seriousness alone."""
    run_id = _completed(submit, worker, programme_asking)
    for finding in signed_in.get(f"{api}/runs/{run_id}/findings").json():
        signed_in.patch(
            f"{api}/findings/{finding['id']}",
            json={"review_status": "confirmed", "review_note": "the delivery must change"},
        )
    _acknowledge(signed_in, api, run_id)

    body = signed_in.get(f"{api}/runs/{run_id}/second-approval").json()

    assert body["required"] is True
    assert body["outstanding"] is False
    assert signed_in.get(f"{api}/runs/{run_id}").json()["can_finalize"] is True


def test_approving_when_nothing_is_waiting_is_refused(
    signed_in: TestClient, api: str, submit: Submit, worker: Worker, programme_asking: str
) -> None:
    run_id = _completed(submit, worker, programme_asking)

    _sign_in(signed_in, api, "second", SECOND)
    refused = signed_in.post(f"{api}/runs/{run_id}/second-approval", json={})

    assert refused.status_code == 422
    assert "waiting for a second approval" in refused.json()["detail"]


def test_the_frozen_report_names_who_gave_the_second_approval(
    signed_in: TestClient, api: str, submit: Submit, worker: Worker, programme_asking: str
) -> None:
    """A report that is evidence of a review should say whose approval it carries."""
    run_id = _completed(submit, worker, programme_asking)
    _wave_through(signed_in, api, run_id)
    _acknowledge(signed_in, api, run_id)
    _sign_in(signed_in, api, "second", SECOND)
    signed_in.post(f"{api}/runs/{run_id}/second-approval", json={"note": "agreed"})

    assert signed_in.post(f"{api}/runs/{run_id}/finalize").status_code == 201
    html = signed_in.get(f"{api}/runs/{run_id}/report").text

    assert "Second approval" in html
    assert "Second Pair Of Eyes" in html
