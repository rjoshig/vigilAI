"""Every admin delete needs the typed word; bulk deletes take one word for many (ADR-032)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _rule(client: TestClient, api: str, name: str) -> int:
    response = client.post(
        f"{api}/admin/compliance-rules",
        json={"name": name, "json_path_contains": f"x.{name}", "reasoning": ""},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_a_delete_without_the_word_is_refused(client: TestClient, api: str) -> None:
    rule_id = _rule(client, api, "one")
    refused = client.delete(f"{api}/admin/compliance-rules/{rule_id}")
    assert refused.status_code == 400
    assert "delete" in refused.json()["detail"]
    assert client.delete(f"{api}/admin/compliance-rules/{rule_id}?confirm=nope").status_code == 400
    assert (
        client.delete(f"{api}/admin/compliance-rules/{rule_id}?confirm=DELETE").status_code == 204
    )


def test_bulk_delete_takes_one_word_for_many_and_reports_the_missing(
    client: TestClient, api: str
) -> None:
    ids = [_rule(client, api, f"r{i}") for i in range(3)]
    refused = client.post(
        f"{api}/admin/compliance-rules/bulk-delete", json={"ids": ids, "confirm": ""}
    )
    assert refused.status_code == 400
    done = client.post(
        f"{api}/admin/compliance-rules/bulk-delete",
        json={"ids": ids[:2] + [9999], "confirm": "delete"},
    )
    assert done.status_code == 200, done.text
    assert done.json() == {"deleted": 2, "missing": [9999]}
    remaining = [r["id"] for r in client.get(f"{api}/admin/compliance-rules").json()]
    assert remaining == ids[2:]
    unknown = client.post(
        f"{api}/admin/nonsense/bulk-delete", json={"ids": [1], "confirm": "delete"}
    )
    assert unknown.status_code == 404


def test_bulk_delete_removes_reference_rows_but_never_a_default_masked_column(
    client: TestClient, api: str
) -> None:
    created = [
        client.post(
            f"{api}/admin/aliases", json={"canonical_name": "score", "alias": f"a{i}"}
        ).json()["id"]
        for i in range(2)
    ]
    done = client.post(
        f"{api}/admin/aliases/bulk-delete", json={"ids": created, "confirm": "delete"}
    )
    assert done.json()["deleted"] == 2
    columns = client.get(f"{api}/admin/masked-columns").json()
    default = next(c for c in columns if c["is_default"])
    kept = client.post(
        f"{api}/admin/masked-columns/bulk-delete",
        json={"ids": [default["id"]], "confirm": "delete"},
    )
    assert kept.json() == {"deleted": 0, "missing": [default["id"]]}


def test_a_compliance_rule_can_be_edited_and_each_edit_bumps_the_version(
    client: TestClient, api: str
) -> None:
    rule_id = _rule(client, api, "ofac")
    edited = client.patch(
        f"{api}/admin/compliance-rules/{rule_id}",
        json={
            "name": "OFAC suppression",
            "json_path_contains": "suppressions.ofac",
            "scope": "programme:AS",
            "reasoning": "Every prescreen delivery suppresses OFAC hits.",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    assert edited.json()["scope"] == "programme:AS"
    again = client.patch(
        f"{api}/admin/compliance-rules/{rule_id}",
        json={"name": "OFAC suppression", "json_path_contains": "suppressions.ofac_list"},
    )
    assert again.json()["version"] == 3
    assert again.json()["json_path_contains"] == "suppressions.ofac_list"
    missing = client.patch(
        f"{api}/admin/compliance-rules/9999", json={"name": "x", "json_path_contains": "y"}
    )
    assert missing.status_code == 404


def test_a_bulk_rule_action_needs_the_action_word_and_reports_failures(
    client: TestClient, api: str
) -> None:
    first = _rule(client, api, "a")
    second = _rule(client, api, "b")
    items = [
        {"rule_kind": "compliance_rule", "id": first},
        {"rule_kind": "compliance_rule", "id": second},
    ]
    refused = client.post(
        f"{api}/admin/rules/bulk", json={"items": items, "action": "disable", "confirm": "delete"}
    )
    assert refused.status_code == 400
    done = client.post(
        f"{api}/admin/rules/bulk",
        json={
            "items": items + [{"rule_kind": "compliance_rule", "id": 9999}],
            "action": "disable",
            "confirm": "disable",
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["changed"] == 2
    assert len(done.json()["failed"]) == 1
    states = {
        r["id"]: r["state"]
        for r in client.get(f"{api}/admin/rules?state=all").json()
        if r["rule_kind"] == "compliance_rule"
    }
    assert states[first] == "disabled" and states[second] == "disabled"
