"""Verdicts become evidence, and evidence changes nothing yet (Phase 6.18a, ADR-043).

`tests/training/test_demotion.py` covers the arithmetic. These cover the wiring: that
recording a verdict updates the signature, that the boundaries of what is shared hold
against a real database, and — the property the whole phase rests on — that in 6.18a
**none of this changes what a reviewer sees**.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.training import demotion


def _run_with_finding(
    factory: sessionmaker[Session],
    *,
    customer: str = "Acme",
    scope: str = "AS",
    rule_ref: str = "check:1",
    finding_type: str = "value_mismatch",
    element_ref: str = "score",
    severity: str = "low",
    shadow: bool = False,
) -> tuple[int, int]:
    """One run carrying one finding, written directly.

    Returns:
        The run id and the finding id.
    """
    with factory() as session:
        run = models.Run(
            customer_name=customer,
            order_number="ORD-1",
            configuration_id="CFG-1",
            scope=scope,
            status="needs_review",
        )
        session.add(run)
        session.flush()
        finding = models.Finding(
            run_id=run.id,
            finding_id="F-01",
            type=finding_type,
            severity=severity,
            title="Something to decide",
            detail="",
            leg="config_reports",
            rule_ref=rule_ref,
            element_ref=element_ref,
            shadow=shadow,
            evidence={},
        )
        session.add(finding)
        session.commit()
        return int(run.id), int(finding.id)


def _review(client: TestClient, api: str, finding_id: int, status: str) -> Any:
    body = {"review_status": status, "review_note": "note" if status == "confirmed" else ""}
    return client.patch(f"{api}/findings/{finding_id}", json=body)


def _wave_through(
    client: TestClient, api: str, factory: sessionmaker[Session], times: int, **over: Any
) -> None:
    for _ in range(times):
        _, finding_id = _run_with_finding(factory, **over)
        assert _review(client, api, finding_id, "false_positive").status_code == 200


def _report(client: TestClient, api: str, **params: str) -> Any:
    response = client.get(f"{api}/admin/demotion-report", params=params)
    assert response.status_code == 200
    return response.json()


# --- the evidence accumulates --------------------------------------------------------


def test_a_verdict_creates_and_updates_the_signature(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _wave_through(client, api, factory, 3)

    report = _report(client, api)
    assert report["counts"][demotion.WATCHING] == 1
    assert report["would_demote"] == []


def test_ten_waves_through_earn_a_would_demote(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _wave_through(client, api, factory, 10)

    report = _report(client, api)
    assert report["counts"][demotion.WOULD_DEMOTE] == 1
    row = report["would_demote"][0]
    assert row["occurrences"] == 10 and row["dismissed"] == 10 and row["upheld"] == 0
    assert row["customer_name"] == "Acme" and row["scope"] == "AS"
    assert row["element_ref"] == "score"
    assert row["reason"]


def test_the_evidence_names_the_runs_it_rests_on(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """A demotion has to be checkable against the deliveries it was learned from."""
    _wave_through(client, api, factory, 10)

    row = _report(client, api)["would_demote"][0]
    assert len(row["justified_by_run_ids"]) == 10
    assert all(isinstance(value, int) for value in row["justified_by_run_ids"])


# --- the boundaries hold --------------------------------------------------------------


def test_one_upheld_finding_blocks_it_permanently(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """The reviewer said it was real once. No number of later waves outranks that."""
    _, first = _run_with_finding(factory)
    assert _review(client, api, first, "confirmed").status_code == 200
    _wave_through(client, api, factory, 20)

    report = _report(client, api)
    assert report["would_demote"] == []
    assert report["counts"][demotion.BLOCKED] == 1
    assert "real" in report["blocked"][0]["reason"]


def test_a_serious_finding_is_never_demoted(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _wave_through(client, api, factory, 15, severity="high")

    report = _report(client, api)
    assert report["would_demote"] == []
    assert report["counts"][demotion.BLOCKED] == 1


def test_trust_does_not_cross_a_customer(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _wave_through(client, api, factory, 9, customer="Acme")
    _wave_through(client, api, factory, 9, customer="Other Co")

    report = _report(client, api)
    assert report["would_demote"] == []
    assert report["counts"][demotion.WATCHING] == 2


def test_trust_does_not_cross_a_programme(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """The chosen boundary: a customer's Archives work learns nothing from their
    solicitation work, because a control genuinely is implemented differently."""
    _wave_through(client, api, factory, 9, scope="AS")
    _wave_through(client, api, factory, 9, scope="ARCHIVE")

    assert _report(client, api)["would_demote"] == []


def test_trust_does_not_cross_what_the_finding_fired_on(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """A blank score column and a blank state column are two things, not one."""
    _wave_through(client, api, factory, 9, element_ref="score")
    _wave_through(client, api, factory, 9, element_ref="state")

    assert _report(client, api)["would_demote"] == []


def test_a_shadow_rules_findings_are_not_evidence(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """A rule nobody was shown cannot have earned anybody's trust.

    Counting shadow findings would let a rule in shadow demote itself on verdicts
    nobody gave it.
    """
    _wave_through(client, api, factory, 12, shadow=True)

    report = _report(client, api)
    assert report["would_demote"] == []


def test_the_report_can_be_narrowed_to_one_customer_or_programme(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _wave_through(client, api, factory, 10, customer="Acme")
    _wave_through(client, api, factory, 10, customer="Other Co")

    assert len(_report(client, api)["would_demote"]) == 2
    narrowed = _report(client, api, customer_name="Acme")["would_demote"]
    assert len(narrowed) == 1 and narrowed[0]["customer_name"] == "Acme"


# --- and it changes nothing ------------------------------------------------------------


def test_a_demotable_finding_is_still_shown_to_the_reviewer(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    """**The property the whole of 6.18a rests on.**

    Ten waves through earn a `would_demote`, and the eleventh delivery still puts the
    finding in front of a person, undecided, exactly as before. Nothing reads the
    state to decide what anybody sees; that is 6.18b's, after this evidence has been
    looked at.
    """
    _wave_through(client, api, factory, 10)
    assert _report(client, api)["counts"][demotion.WOULD_DEMOTE] == 1

    run_id, _ = _run_with_finding(factory)
    shown = client.get(f"{api}/runs/{run_id}/findings").json()

    assert len(shown) == 1
    assert shown[0]["review_status"] == "undecided"
    assert _report(client, api)["shadow"] is True


def test_the_report_is_empty_before_anybody_decides_anything(
    client: TestClient, api: str, factory: sessionmaker[Session]
) -> None:
    _run_with_finding(factory)

    report = _report(client, api)
    assert report["would_demote"] == [] and report["blocked"] == []
    assert sum(report["counts"].values()) == 0
