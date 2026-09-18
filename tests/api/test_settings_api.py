"""Tests for the runtime settings endpoints (ADR-023).

These cover what a person can do wrong from the console: change something they should
not be able to, set a value out of range, or leak a secret by reading it back.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from vigilai.config.store import invalidate

Submit = Callable[..., Any]


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    """Keep one test's overrides out of the next test's cache."""
    invalidate()
    yield
    invalidate()


def test_the_console_lists_every_setting_with_its_source(client: TestClient, api: str) -> None:
    """Seeing the layer beside the value is what prevents an hour of confusion."""
    groups = client.get(f"{api}/admin/settings").json()
    names = [group["name"] for group in groups]
    assert names == ["Model", "Login", "Throughput", "Uploads", "Retention", "Platform"]

    settings = {s["key"]: s for group in groups for s in group["settings"]}
    assert settings["llm.max_tokens"]["source"] in ("env", "default")
    assert settings["platform.database_url"]["editable"] is False
    assert settings["llm.api_key"]["value"] is None


def test_saving_a_setting_takes_effect_on_the_next_request(client: TestClient, api: str) -> None:
    """Immediately, not at the next deployment."""
    saved = client.post(f"{api}/admin/settings", json={"key": "queue.per_order_limit", "value": 7})
    assert saved.status_code == 200, saved.text
    assert saved.json()["value"] == 7
    assert saved.json()["source"] == "admin"

    groups = client.get(f"{api}/admin/settings").json()
    settings = {s["key"]: s for group in groups for s in group["settings"]}
    assert settings["queue.per_order_limit"]["value"] == 7


def test_reverting_puts_the_setting_back_under_the_environment(
    client: TestClient, api: str
) -> None:
    """Revert names what it will revert to, then does that."""
    client.post(f"{api}/admin/settings", json={"key": "retention.days", "value": 30})
    reverted = client.delete(f"{api}/admin/settings/retention.days")
    assert reverted.status_code == 200
    assert reverted.json()["value"] == 90
    assert reverted.json()["source"] in ("env", "default")


def test_a_read_only_setting_is_refused(client: TestClient, api: str) -> None:
    """The console must not be able to change how it reaches its own database."""
    response = client.post(
        f"{api}/admin/settings", json={"key": "platform.database_url", "value": "sqlite://x"}
    )
    assert response.status_code == 422
    assert "not editable" in response.json()["detail"]


def test_an_out_of_range_value_is_refused(client: TestClient, api: str) -> None:
    """Bounds are declared once and enforced on the way in."""
    response = client.post(f"{api}/admin/settings", json={"key": "llm.max_tokens", "value": 1})
    assert response.status_code == 422


def test_an_unknown_setting_is_a_404(client: TestClient, api: str) -> None:
    """Every setting is declared in one place, so an unknown key is a mistake."""
    assert (
        client.post(f"{api}/admin/settings", json={"key": "nope.nope", "value": 1}).status_code
        == 404
    )


def test_a_secret_needs_a_master_key_and_never_comes_back(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing to store it is better than pretending it is protected."""
    monkeypatch.delenv("VIGILAI_SECRET_KEY", raising=False)
    refused = client.post(f"{api}/admin/settings", json={"key": "llm.api_key", "value": "sk-nope"})
    assert refused.status_code == 409
    assert "VIGILAI_SECRET_KEY" in refused.json()["detail"]

    monkeypatch.setenv("VIGILAI_SECRET_KEY", Fernet.generate_key().decode())
    invalidate()
    stored = client.post(
        f"{api}/admin/settings", json={"key": "llm.api_key", "value": "sk-live-key-4321"}
    )
    assert stored.status_code == 200, stored.text
    body = stored.json()
    assert body["value"] is None
    assert body["is_set"] is True
    assert body["last4"] == "4321"

    everything = client.get(f"{api}/admin/settings").text
    assert "sk-live-key-4321" not in everything


def test_the_change_history_records_who_and_from_what(client: TestClient, api: str) -> None:
    """Revert is a button because the old value was kept."""
    client.post(f"{api}/admin/settings", json={"key": "uploads.max_mb", "value": 25})
    history = client.get(f"{api}/admin/settings/history").json()
    assert history
    entry = next(row for row in history if row["key"] == "uploads.max_mb")
    assert entry["old_value"] == 50
    assert entry["new_value"] == 25


def test_the_model_connection_test_reports_what_happened(client: TestClient, api: str) -> None:
    """Answering 'did I type the key right' beats a run failing at stage two."""
    response = client.post(f"{api}/admin/settings/test-model")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert body["ok"] is True


def test_the_start_rate_limit_refuses_rather_than_queues(
    client: TestClient, api: str, submit: Submit
) -> None:
    """A person standing there needs a clear answer, not an invisible queue."""
    assert (
        client.post(
            f"{api}/admin/settings", json={"key": "queue.starts_per_window", "value": 1}
        ).status_code
        == 200
    )
    assert submit().status_code == 201
    limited = submit(order_number="ORD-SECOND")
    assert limited.status_code == 429
    assert "configured limit" in limited.json()["detail"]


def test_the_per_order_cap_is_admin_controlled(
    client: TestClient, api: str, submit: Submit
) -> None:
    """The cap was a constant; now it is a setting, and it still holds."""
    client.post(f"{api}/admin/settings", json={"key": "queue.per_order_limit", "value": 1})
    client.post(f"{api}/admin/settings", json={"key": "queue.starts_per_window", "value": 100})
    assert submit().status_code == 201
    second = submit(rerun_reason="a second one for the same order")
    assert second.status_code == 409
