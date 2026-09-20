"""An alternate path lets a rule find a control a customer names differently (6.15)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _rule(client: TestClient, api: str, **extra: Any) -> dict[str, Any]:
    """Create a compliance rule the way the console does."""
    payload = {
        "name": "OFAC suppression",
        "json_path_contains": "suppressions.ofac",
        "reasoning": "Every delivery must screen against the SDN list.",
        **extra,
    }
    response = client.post(f"{api}/admin/compliance-rules", json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_a_rule_round_trips_its_alternates(client: TestClient, api: str) -> None:
    """What an administrator types has to come back."""
    created = _rule(client, api, alternates=["suppressions.sdn_screening", "exclusions.ofac"])
    assert created["alternates"] == ["suppressions.sdn_screening", "exclusions.ofac"]

    listed = client.get(f"{api}/admin/compliance-rules").json()
    assert listed[0]["alternates"] == ["suppressions.sdn_screening", "exclusions.ofac"]


def test_a_rule_without_alternates_is_unchanged(client: TestClient, api: str) -> None:
    """Configuring nothing changes nothing: every existing rule keeps working."""
    created = _rule(client, api)
    assert created["alternates"] == []


def test_blank_alternates_are_dropped(client: TestClient, api: str) -> None:
    """A trailing empty box should not become a path that matches everything."""
    created = _rule(client, api, alternates=["  ", "exclusions.ofac", ""])
    assert created["alternates"] == ["exclusions.ofac"]
