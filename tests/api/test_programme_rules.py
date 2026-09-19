"""Programme rules and the programme classification check (ADR-026).

A programme rule is a sentence with a strictness. The model reads for breaches; code
sets the severity. The classification check is a grep, and it says so.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.pipeline.context import RunContext
from greenlight_ai.pipeline.guidance import RunGuidance
from greenlight_ai.pipeline.s7_reports import _check_programme
from greenlight_ai.rules.schema import Finding

Submit = Callable[..., Any]


def _rule(client: TestClient, api: str, **fields: Any) -> Any:
    body = {
        "scope_code": "AS",
        "title": "Opt-outs excluded",
        "text": "Every prescreen delivery excludes opt-outs.",
        "strictness": "must",
        **fields,
    }
    return client.post(f"{api}/admin/programme-rules", json=body)


# --- the admin surface --------------------------------------------------------------


def test_a_programme_holds_several_rules_each_with_its_own_strictness(
    client: TestClient, api: str
) -> None:
    client.get(f"{api}/admin/scopes")
    assert _rule(client, api).status_code == 201
    assert _rule(client, api, title="Bands as in the OSL", strictness="should").status_code == 201
    assert (
        _rule(client, api, title="Cadence", strictness="advisory", scope_code="AM").status_code
        == 201
    )

    rules = client.get(f"{api}/admin/programme-rules?scope_code=AS").json()
    assert [r["strictness"] for r in rules] == ["must", "should"]
    assert all(r["state"] == "active" for r in rules)
    assert len(client.get(f"{api}/admin/programme-rules").json()) == 3


def test_a_rule_for_an_unknown_programme_is_refused(client: TestClient, api: str) -> None:
    assert _rule(client, api, scope_code="NOPE").status_code == 404


def test_a_rule_can_be_reworded_and_appears_on_the_rules_screen(
    client: TestClient, api: str
) -> None:
    client.get(f"{api}/admin/scopes")
    created = _rule(client, api).json()
    edited = client.patch(
        f"{api}/admin/programme-rules/{created['id']}",
        json={
            "scope_code": "AS",
            "title": "Opt-outs excluded",
            "text": "Reworded.",
            "strictness": "advisory",
        },
    )
    assert edited.status_code == 200 and edited.json()["strictness"] == "advisory"

    rows = client.get(f"{api}/admin/rules?state=active").json()
    mine = [r for r in rows if r["rule_kind"] == "programme_rule"]
    assert len(mine) == 1 and mine[0]["name"] == "Opt-outs excluded"

    off = client.post(
        f"{api}/admin/rules/programme_rule/{created['id']}/action",
        json={"action": "disable", "confirm": "disable"},
    )
    assert off.status_code == 200 and off.json()["state"] == "disabled"


def test_keywords_are_seeded_and_editable(client: TestClient, api: str) -> None:
    scopes = {s["code"]: s for s in client.get(f"{api}/admin/scopes").json()}
    assert "prescreen" in scopes["AS"]["keywords"]
    saved = client.post(
        f"{api}/admin/scopes",
        json={"code": "AS", "label": "Account Solicitation", "keywords": ["prescreen", " ITA "]},
    )
    assert saved.status_code == 201
    assert saved.json()["keywords"] == ["prescreen", "ITA"]


# --- the classification check -------------------------------------------------------


def _build(cls: Any, **given: Any) -> Any:
    """Construct a parser dataclass with harmless defaults for whatever is not given.

    The parsed-document dataclasses carry several required fields the classification
    check never reads; filling them generically keeps this test about the check.
    """
    import dataclasses
    from pathlib import Path

    values: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in given:
            values[f.name] = given[f.name]
        elif (
            f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        ):
            continue
        elif f.type in ("str", str):
            values[f.name] = ""
        elif f.type in ("int", int):
            values[f.name] = 1
        elif "Path" in str(f.type):
            values[f.name] = Path("x")
        else:
            values[f.name] = ()
    return cls(**values)


def _context(osl_text: str, declared: str) -> RunContext:
    """A minimal context with one OSL section carrying the given text."""
    from pathlib import Path

    from greenlight_ai.parsers.base import ConfigDocument, OslDocument, OslSection

    context = RunContext(
        run_id="t",
        osl_path=Path("x.docx"),
        config_path=Path("x.json"),
        report_paths={},
        client=None,  # type: ignore[arg-type]
        guidance=RunGuidance(
            scope_code=declared,
            scope_label=declared,
            programme_keywords={
                "AS": ("prescreen", "firm offer", "invitation to apply"),
                "AM": ("account monitoring", "portfolio review"),
            },
        ),
    )
    section = _build(OslSection, number="1", heading="Scope", level=1, paragraphs=(osl_text,))
    context.osl = _build(OslDocument, sections=(section,))
    context.config = _build(ConfigDocument, blocks=())
    return context


def test_declared_programme_found_in_the_inputs_raises_nothing() -> None:
    context = _context("This prescreen campaign delivers firm offers to CA.", "AS")
    _check_programme(context)
    assert context.findings == []


def test_declared_programme_absent_and_another_present_is_a_high_finding() -> None:
    context = _context("Account monitoring of the existing portfolio review set.", "AS")
    _check_programme(context)
    assert len(context.findings) == 1
    finding: Finding = context.findings[0]
    assert finding.type == "programme_mismatch"
    assert finding.severity == "high"
    assert "read like AM" in finding.title
    assert "prescreen" in finding.detail


def test_declared_programme_absent_with_no_other_signal_is_a_review_item() -> None:
    context = _context("Deliver name and balance for all accounts.", "AS")
    _check_programme(context)
    assert context.findings[0].severity == "review"


# --- end to end: the model reads, code grades ---------------------------------------


def test_a_breach_carries_the_rule_s_strictness_as_its_severity(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    worker: Any,
    submit: Submit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model names the rule; the severity comes from what the administrator set."""
    import json

    client.get(f"{api}/admin/scopes")
    must = _rule(client, api).json()
    advisory = _rule(
        client, api, title="Bands", text="Bands as in the OSL.", strictness="advisory"
    ).json()

    from synthetic_model import build_client

    real_build = build_client

    def build_with_programme(settings: Any, **kw: Any) -> Any:
        c = real_build(settings, **kw)
        c.register_text(
            "s8_programme",
            json.dumps(
                {
                    "breaches": [
                        {
                            "rule_id": must["id"],
                            "evidence": "no opt-out filter",
                            "reason": "missing",
                            "confidence": 0.9,
                        },
                        {
                            "rule_id": advisory["id"],
                            "evidence": "bands renamed",
                            "reason": "renamed",
                            "confidence": 0.8,
                        },
                        {
                            "rule_id": 99999,
                            "evidence": "made up",
                            "reason": "invented",
                            "confidence": 0.9,
                        },
                    ]
                }
            ),
        )
        return c

    import greenlight_ai.worker.runner as runner

    monkeypatch.setattr(
        runner,
        "build_client",
        lambda settings, cache=None, call_log=None, **_: build_with_programme(
            settings, cache=cache, call_log=call_log
        ),
    )

    assert submit(scope="AS").status_code == 201
    worker.run_once()
    with factory() as session:
        rows = list(
            session.execute(
                sa.select(models.Finding).where(models.Finding.type == "programme_rule_violation")
            ).scalars()
        )
    by_ref = {r.rule_ref: r.severity for r in rows}
    assert by_ref == {
        f"programme_rule:{must['id']}": "high",
        f"programme_rule:{advisory['id']}": "low",
    }
