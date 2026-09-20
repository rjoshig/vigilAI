"""Field labels are versioned like every other definition (Phase 6.14b, ADR-029).

Labels were the one definition without a history, which meant a wrong one could be
corrected but never traced. These cover the round trip: change, list, revert.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _add(client: TestClient, api: str, label: str, scope: str = "everywhere") -> int:
    """Add a label the way the console does."""
    response = client.post(
        f"{api}/admin/field-labels",
        json={"canonical": "credit_date", "label": label, "scope": scope},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_every_change_writes_a_version(client: TestClient, api: str) -> None:
    """Adding, switching off and deleting each leave a trace."""
    label_id = _add(client, api, "Cycle date")
    client.post(f"{api}/admin/field-labels/{label_id}/active?active=false")

    history = client.get(f"{api}/admin/versions/field-label/credit_date").json()
    assert len(history) == 2
    # Newest first, the way every other history is ordered.
    assert "switched off" in history[0]["summary"]
    assert "added" in history[1]["summary"]


def test_reverting_brings_a_deleted_label_back(client: TestClient, api: str) -> None:
    """The point of a history: undo without retyping."""
    _add(client, api, "Vintage")
    after_add = client.get(f"{api}/admin/versions/field-label/credit_date").json()[0]["version"]

    label_id = client.get(f"{api}/admin/field-labels").json()[-1]["id"]
    client.delete(f"{api}/admin/field-labels/{label_id}?confirm=delete")
    assert not any(
        row["label"] == "Vintage"
        for row in client.get(f"{api}/admin/field-labels").json()
        if not row["is_builtin"]
    )

    reverted = client.post(
        f"{api}/admin/versions/field-label/credit_date/{after_add}/revert",
        json={"confirm": "revert"},
    )
    assert reverted.status_code == 200, reverted.text
    assert any(
        row["label"] == "Vintage"
        for row in client.get(f"{api}/admin/field-labels").json()
        if not row["is_builtin"]
    )


def test_a_revert_is_itself_a_version(client: TestClient, api: str) -> None:
    """Nothing is ever lost, including the state somebody reverted away from."""
    _add(client, api, "Data date")
    first = client.get(f"{api}/admin/versions/field-label/credit_date").json()[0]["version"]
    _add(client, api, "Snapshot taken")

    client.post(
        f"{api}/admin/versions/field-label/credit_date/{first}/revert",
        json={"confirm": "revert"},
    )
    history = client.get(f"{api}/admin/versions/field-label/credit_date").json()
    assert f"reverted to version {first}" in history[0]["summary"]
    assert len(history) == 3
