"""A replay that replays (Phase 6.13e).

Before this milestone the console said "runs examined" about a count of findings whose
titles happened to contain the rule's field name. It examined nothing, said nothing at
all about a check or a compliance rule, and an administrator approving a rule on the
strength of it was reading a number that did not mean what it said.

Replay now parses each finalized run's stored reports again and runs the evaluator that
would run the rule in the pipeline. These tests hold it to that: a rule that a run
breaks fires, a rule the same run satisfies does not, a malformed expression never
becomes a rule at all, and the work happens in the worker rather than in the request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from greenlight_ai.db import models
from greenlight_ai.worker.replay import replay_candidate

Submit = Callable[..., Any]


def _finalized_run(
    client: TestClient,
    api: str,
    worker: Any,
    submit: Submit,
    clear_gate: Callable[..., None],
) -> int:
    """One run through the real pipeline, finalized, with its files still on disk."""
    run_id = int(submit().json()["run_id"])
    while worker.run_once():
        pass
    clear_gate(run_id)
    finalized = client.post(f"{api}/runs/{run_id}/finalize")
    assert finalized.status_code in (200, 201), finalized.text
    return run_id


def _candidate(
    factory: sessionmaker[Session], target_kind: str, body: dict[str, Any]
) -> models.RuleCandidate:
    with factory() as session:
        row = models.RuleCandidate(
            name=str(body.get("field") or body.get("name") or "candidate"),
            target_kind=target_kind,
            body=body,
            status="draft",
        )
        session.add(row)
        session.commit()
        return row


def _replay(
    factory: sessionmaker[Session], data_dir: Path, target_kind: str, body: dict[str, Any]
) -> dict[str, Any]:
    candidate = _candidate(factory, target_kind, body)
    with factory() as session:
        row = session.get(models.RuleCandidate, candidate.id)
        assert row is not None
        return replay_candidate(session, row, data_dir, limit=5)


# --- it evaluates, rather than counting titles ---------------------------------------------


def test_a_constraint_the_run_breaks_fires_and_says_what_it_found(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    worker: Any,
    submit: Submit,
    clear_gate: Callable[..., None],
    db_settings: Any,
) -> None:
    run_id = _finalized_run(client, api, worker, submit, clear_gate)

    result = _replay(
        factory,
        db_settings.data_dir,
        "field_constraint",
        {
            "field": "SCORE_V3",
            "constraint": "range",
            "minimum": 0,
            "maximum": 700,
            "report_kinds": ["dirt"],
        },
    )

    assert result["runs_examined"] == 1, "the run was read, not counted"
    assert result["would_fire_on"] == [run_id]
    assert result["examples"], "it says what it would have found"
    assert result["evaluated"] is True


def test_a_constraint_the_run_satisfies_does_not_fire(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    worker: Any,
    submit: Submit,
    clear_gate: Callable[..., None],
    db_settings: Any,
) -> None:
    _finalized_run(client, api, worker, submit, clear_gate)

    result = _replay(
        factory,
        db_settings.data_dir,
        "field_constraint",
        {"field": "ST", "constraint": "not_blank", "report_kinds": ["dirt"]},
    )

    assert result["runs_examined"] == 1
    assert result["would_fire_on"] == []


def test_a_compliance_rule_is_replayed_against_the_configuration(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    worker: Any,
    submit: Submit,
    clear_gate: Callable[..., None],
    db_settings: Any,
) -> None:
    """The old count said nothing at all about a compliance rule."""
    run_id = _finalized_run(client, api, worker, submit, clear_gate)

    missing = _replay(
        factory,
        db_settings.data_dir,
        "compliance_rule",
        {"name": "audit_trail", "json_path_contains": "audit.trail.enabled"},
    )
    present = _replay(
        factory,
        db_settings.data_dir,
        "compliance_rule",
        {"name": "rules", "json_path_contains": "rules"},
    )

    assert missing["would_fire_on"] == [run_id], "no configuration path carries it"
    assert present["would_fire_on"] == [], "the configuration has this one"


def test_a_check_whose_values_the_run_does_not_carry_is_not_counted_as_firing(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    worker: Any,
    submit: Submit,
    clear_gate: Callable[..., None],
    db_settings: Any,
) -> None:
    """A value a report does not carry is a run the rule says nothing about."""
    _finalized_run(client, api, worker, submit, clear_gate)

    result = _replay(
        factory,
        db_settings.data_dir,
        "check",
        {"name": "impossible", "expression": "no_such_value > 0"},
    )

    assert result["would_fire_on"] == []
    assert result["runs_examined"] == 1


def test_a_replay_with_no_finalized_runs_says_so_rather_than_implying_a_verdict(
    factory: sessionmaker[Session], db_settings: Any
) -> None:
    result = _replay(
        factory,
        db_settings.data_dir,
        "field_constraint",
        {"field": "ST", "constraint": "not_blank"},
    )

    assert result["runs_examined"] == 0
    assert result["would_fire_on"] == []
    assert result["note"]


# --- it runs in the worker -------------------------------------------------------------------


def test_asking_for_a_replay_queues_it_and_the_worker_fills_it_in(
    client: TestClient,
    api: str,
    factory: sessionmaker[Session],
    worker: Any,
    submit: Submit,
    clear_gate: Callable[..., None],
) -> None:
    _finalized_run(client, api, worker, submit, clear_gate)
    candidate = _candidate(
        factory,
        "field_constraint",
        {
            "field": "SCORE_V3",
            "constraint": "range",
            "minimum": 0,
            "maximum": 700,
            "report_kinds": ["dirt"],
        },
    )

    asked = client.post(f"{api}/admin/candidates/{candidate.id}/replay")
    assert asked.status_code == 200, asked.text
    assert asked.json()["replay"]["status"] == "running", "the console has something to poll"

    with factory() as session:
        queued = session.execute(
            sa.select(models.Job.task).where(models.Job.status == "queued")
        ).scalars()
        assert "replay" in set(queued)

    while worker.run_once():
        pass

    filled = client.get(f"{api}/admin/candidates").json()
    ours = next(row for row in filled if row["id"] == candidate.id)
    assert ours["replay"]["evaluated"] is True
    assert ours["replay"]["runs_examined"] == 1


def test_a_replay_for_a_candidate_that_is_gone_does_not_fail_the_worker(
    factory: sessionmaker[Session], worker: Any
) -> None:
    from greenlight_ai.db.queue import JobQueue

    with factory() as session:
        JobQueue(session, True).enqueue("replay", payload={"candidate_id": 9999})
        session.commit()

    assert worker.run_once() is True, "the job was claimed and finished, not retried forever"


# --- a malformed expression never becomes a rule ------------------------------------------


def test_a_drafted_check_with_a_bad_expression_is_refused_at_draft_time() -> None:
    """Refused where it is written, rather than becoming a finding nobody can explain."""
    from greenlight_ai.llm.prompts.schemas import SynthesizedRule
    from greenlight_ai.training.synthesis import validate_rule

    bad = SynthesizedRule(
        name="dangerous", target_kind="check", expression="__import__('os').system('ls')"
    )
    assert "cannot be evaluated" in validate_rule(bad, [])

    good = SynthesizedRule(
        name="fine", target_kind="check", expression="billing_count <= delivered_count"
    )
    assert validate_rule(good, []) == ""


def test_an_approved_constraint_keeps_the_parameter_the_model_gave_it(
    factory: sessionmaker[Session],
) -> None:
    """Found while replaying: approval read a key the model never answers with.

    The model returns ``values``, ``minimum``, ``maximum`` and ``pattern``, named after
    the constraint so its answer stays checkable. Approval read ``value``, which is not
    one of them, so every learned allowed-values, range and format constraint went live
    with no parameter and evaluated to "could not be checked" for ever.
    """
    from greenlight_ai.training.synthesis import approve, constraint_value

    assert constraint_value({"constraint": "allowed_values", "values": ["IL", "AZ"]}) == [
        "IL",
        "AZ",
    ]
    assert constraint_value({"constraint": "range", "minimum": 0, "maximum": 700}) == {
        "min": 0,
        "max": 700,
    }
    assert constraint_value({"constraint": "format", "pattern": r"\d{4}"}) == r"\d{4}"
    assert constraint_value({"constraint": "not_blank"}) is None

    with factory() as session:
        candidate = models.RuleCandidate(
            name="states_in_scope",
            target_kind="field_constraint",
            body={
                "field": "ST",
                "constraint": "allowed_values",
                "values": ["IL", "AZ"],
                "report_kinds": ["dirt"],
            },
            status="draft",
        )
        session.add(candidate)
        session.flush()
        approve(session, candidate, actor="a test")
        session.commit()

        stored = session.execute(sa.select(models.FieldConstraint)).scalar_one()
        assert stored.value == ["IL", "AZ"], "the rule went live able to check something"
