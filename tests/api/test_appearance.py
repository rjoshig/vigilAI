"""Tests for the public appearance endpoint (Phase 6.6, ADR-031)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_the_default_theme_comes_from_the_environment_then_the_built_in(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from greenlight_ai.config import store

    monkeypatch.delenv("GREENLIGHT_AI_UI_THEME", raising=False)
    store.invalidate()
    body = client.get(f"{api}/appearance").json()
    assert body == {
        "theme": "classic-teal-navy",
        "locked": False,
        "palettes": ["classic-teal-navy", "classic-teal", "light-blue-yellow", "default"],
    }

    monkeypatch.setenv("GREENLIGHT_AI_UI_THEME", "classic-teal")
    store.invalidate()
    assert client.get(f"{api}/appearance").json()["theme"] == "classic-teal"


def test_the_console_overrides_the_environment_and_can_lock(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from greenlight_ai.config import store

    monkeypatch.setenv("GREENLIGHT_AI_UI_THEME", "classic-teal")
    saved = client.post(f"{api}/admin/settings", json={"key": "ui.theme", "value": "default"})
    assert saved.status_code == 200, saved.text
    client.post(f"{api}/admin/settings", json={"key": "ui.theme_locked", "value": True})
    store.invalidate()
    body = client.get(f"{api}/appearance").json()
    assert (body["theme"], body["locked"]) == ("default", True)

    refused = client.post(f"{api}/admin/settings", json={"key": "ui.theme", "value": "neon"})
    assert refused.status_code == 422
