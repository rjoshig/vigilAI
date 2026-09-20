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
    # Locked out of the box (Phase 6.14e): everyone reviewing a delivery sees the same
    # colours unless an administrator decides otherwise.
    assert body == {
        "theme": "classic-teal-navy",
        "locked": True,
        "palettes": ["classic-teal-navy", "classic-teal", "light-blue-yellow", "default"],
        "tooltips": True,
        "tagline": "Nothing ships without a green light.",
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


def test_unlocking_restores_the_picker_in_both_apps(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new default is one switch away from the old behaviour (Phase 6.14e).

    Locking by default only reads as a deliberate choice if unlocking is obvious and
    complete, so this asserts the whole way back rather than only the way in.
    """
    from greenlight_ai.config import store

    monkeypatch.delenv("GREENLIGHT_AI_UI_THEME", raising=False)
    store.invalidate()
    assert client.get(f"{api}/appearance").json()["locked"] is True

    saved = client.post(f"{api}/admin/settings", json={"key": "ui.theme_locked", "value": False})
    assert saved.status_code == 200, saved.text
    store.invalidate()
    assert client.get(f"{api}/appearance").json()["locked"] is False


def test_the_console_can_switch_the_explanations_off(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On by default, and off is one switch (Phase 6.14d)."""
    from greenlight_ai.config import store

    monkeypatch.delenv("GREENLIGHT_AI_UI_TOOLTIPS", raising=False)
    store.invalidate()
    assert client.get(f"{api}/appearance").json()["tooltips"] is True

    saved = client.post(f"{api}/admin/settings", json={"key": "ui.tooltips", "value": False})
    assert saved.status_code == 200, saved.text
    store.invalidate()
    assert client.get(f"{api}/appearance").json()["tooltips"] is False


def test_the_tagline_comes_from_the_console(
    client: TestClient, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the sidebar says under the mark, without a deploy (Phase 6.14h)."""
    from greenlight_ai.config import store

    saved = client.post(
        f"{api}/admin/settings",
        json={"key": "ui.tagline", "value": "QC for Global Delivery."},
    )
    assert saved.status_code == 200, saved.text
    store.invalidate()
    assert client.get(f"{api}/appearance").json()["tagline"] == "QC for Global Delivery."
