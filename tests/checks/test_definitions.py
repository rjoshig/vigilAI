"""Tests for ``checks/definitions.py``: which runs a definition's scope covers."""

from __future__ import annotations

import pytest

from greenlight_ai.checks.definitions import CheckDefinition, ComplianceRule, in_scope


@pytest.mark.parametrize(
    ("scope", "customer", "programme", "expected"),
    [
        ("all", "Acme", "AS", True),
        ("all", "", "", True),
        ("Acme", "Acme", "AM", True),
        ("Acme", "Harbor", "AM", False),
        ("programme:AS", "Acme", "AS", True),
        ("programme:as", "Acme", "AS", True),
        ("programme:AS", "Acme", "AM", False),
        ("programme:AS", "Acme", "", False),
        ("programme:", "Acme", "", False),
    ],
)
def test_in_scope(scope: str, customer: str, programme: str, expected: bool) -> None:
    assert in_scope(scope, customer, programme) is expected


def test_definitions_delegate_to_in_scope_and_honour_is_active() -> None:
    check = CheckDefinition(name="c", expression="1 == 1", scope="programme:AM")
    rule = ComplianceRule(name="r", json_path_contains="x", scope="programme:AM")
    assert check.applies_to("Acme", "AM") and rule.applies_to("Acme", "AM")
    assert not check.applies_to("Acme", "AS") and not rule.applies_to("Acme", "AS")
    assert not CheckDefinition(name="c", scope="all", is_active=False).applies_to("Acme", "AM")
    # The old one-argument call still works: no programme means programme scopes never match.
    assert ComplianceRule(name="r", json_path_contains="x").applies_to("Acme")


def test_a_shadow_check_runs_and_a_disabled_one_does_not() -> None:
    """ADR-021: shadow rules run and are counted; their findings are shown to nobody."""
    shadow = CheckDefinition(name="c", expression="1 == 1", is_active=False, state="shadow")
    disabled = CheckDefinition(name="c", expression="1 == 1", is_active=False, state="disabled")
    assert shadow.applies_to("Acme")
    assert not disabled.applies_to("Acme")
