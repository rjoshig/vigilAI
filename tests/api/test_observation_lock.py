"""Feedback is submitted once, and withdrawn rather than deleted (Phase 6.14k).

An observation an administrator has read — and may have drafted a rule from — should
not change underneath them, so the author's form locks after they send it. What that
costs is the ability to fix a mistake, which is why an administrator can withdraw one
and free the author to write a fresh one.

Withdrawn, not deleted: nothing in the training record is ever deleted (CLAUDE.md hard
rule 8). What somebody said is worth more than the row it occupies.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def observation(client: TestClient, api: str, submit: Callable[..., Any]) -> int:
    """One submitted observation, with Train AI mode on."""
    client.post(f"{api}/admin/settings", json={"key": "training.enabled", "value": True})
    response = client.post(
        f"{api}/observations",
        json={
            "kind": "reconciliation",
            "statement": "The account status column is never blank for this customer.",
            "expectation": "Flag any blank account status.",
            "severity_hint": "medium",
            "scope_hint": "customer",
            "anchors": [],
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_an_administrator_can_correct_the_wording(
    client: TestClient, api: str, observation: int
) -> None:
    """The author is locked out; somebody still has to be able to fix a typo."""
    response = client.patch(
        f"{api}/observations/{observation}",
        json={
            "kind": "reconciliation",
            "statement": "The account status column is never blank for Acme.",
            "expectation": "Flag any blank account status.",
            "severity_hint": "medium",
            "scope_hint": "customer",
            "anchors": [],
        },
    )
    assert response.status_code == 200, response.text
    assert "Acme" in response.json()["statement"]
    # The trail survives the convenience.
    assert response.json()["version"] == 2


def test_withdrawing_takes_it_off_every_screen(
    client: TestClient, api: str, observation: int
) -> None:
    """What withdrawing is for."""
    assert any(o["id"] == observation for o in client.get(f"{api}/observations").json())

    response = client.post(f"{api}/admin/observations/{observation}/withdraw")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "withdrawn"

    assert not any(o["id"] == observation for o in client.get(f"{api}/observations").json())


def test_a_withdrawn_observation_is_not_deleted(
    client: TestClient, api: str, observation: int
) -> None:
    """Hard rule 8: the row survives, and can still be asked for by name."""
    client.post(f"{api}/admin/observations/{observation}/withdraw")
    kept = client.get(f"{api}/observations?status=withdrawn").json()
    assert [o["id"] for o in kept] == [observation]
    assert "withdrawn by" in kept[0]["status_note"]


def test_the_author_may_submit_again_afterwards(
    client: TestClient, api: str, observation: int
) -> None:
    """The whole point: a mistake does not cost somebody their one piece of feedback."""
    client.post(f"{api}/admin/observations/{observation}/withdraw")
    again = client.post(
        f"{api}/observations",
        json={
            "kind": "reconciliation",
            "statement": "What I actually meant to say about account status.",
            "expectation": "Flag any blank account status.",
            "severity_hint": "medium",
            "scope_hint": "customer",
            "anchors": [],
        },
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != observation
