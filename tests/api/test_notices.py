"""The notices endpoint each app polls, and the console that schedules them (6.14g)."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient


def _window(hours_from: int = -1, hours_to: int = 1) -> dict[str, str]:
    """A start and end around now, as the form submits them."""
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "starts_at": (now + dt.timedelta(hours=hours_from)).isoformat(),
        "ends_at": (now + dt.timedelta(hours=hours_to)).isoformat(),
    }


def test_no_notices_by_default(client: TestClient, api: str) -> None:
    """A banner that is always there is not read; empty is the normal state."""
    assert client.get(f"{api}/notices?audience=user").json() == []


def test_a_scheduled_notice_reaches_its_audience(client: TestClient, api: str) -> None:
    """The point of the feature, end to end."""
    created = client.post(
        f"{api}/admin/announcements",
        json={
            "level": "warning",
            "audience": "user",
            "message": "Maintenance starts at 11pm on the 6th.",
            **_window(),
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["showing_now"] is True

    shown = client.get(f"{api}/notices?audience=user").json()
    assert [n["message"] for n in shown] == ["Maintenance starts at 11pm on the 6th."]
    assert shown[0]["level"] == "warning"
    # Scheduled for users only, so the console does not carry it.
    assert client.get(f"{api}/notices?audience=admin").json() == []


def test_a_future_notice_is_stored_but_not_shown(client: TestClient, api: str) -> None:
    """Scheduling it for tomorrow means tomorrow."""
    created = client.post(
        f"{api}/admin/announcements",
        json={"level": "info", "audience": "both", "message": "Later.", **_window(24, 48)},
    )
    assert created.status_code == 201
    assert created.json()["showing_now"] is False
    assert client.get(f"{api}/notices?audience=user").json() == []


def test_switching_one_off_takes_it_down(client: TestClient, api: str) -> None:
    """Without losing the row, so a recurring message is not retyped."""
    notice_id = client.post(
        f"{api}/admin/announcements",
        json={"level": "info", "audience": "both", "message": "Up.", **_window()},
    ).json()["id"]
    assert client.get(f"{api}/notices?audience=user").json() != []

    client.post(f"{api}/admin/announcements/{notice_id}/active?active=false")
    assert client.get(f"{api}/notices?audience=user").json() == []
    assert len(client.get(f"{api}/admin/announcements").json()) == 1


def test_a_sixth_notice_is_refused_with_a_reason(client: TestClient, api: str) -> None:
    """The reading limit, surfaced as a message somebody can act on."""
    for index in range(5):
        response = client.post(
            f"{api}/admin/announcements",
            json={
                "level": "info",
                "audience": "both",
                "message": f"Notice {index}.",
                **_window(),
            },
        )
        assert response.status_code == 201, response.text

    refused = client.post(
        f"{api}/admin/announcements",
        json={"level": "info", "audience": "both", "message": "One more.", **_window()},
    )
    assert refused.status_code == 422
    assert "skimmed" in refused.json()["detail"]


def test_a_backwards_window_is_refused(client: TestClient, api: str) -> None:
    """A typo in the dates should not store a notice that can never show."""
    refused = client.post(
        f"{api}/admin/announcements",
        json={"level": "info", "audience": "both", "message": "Oops.", **_window(1, -1)},
    )
    assert refused.status_code == 422
    assert "before it started" in refused.json()["detail"]
