#!/usr/bin/env python3
"""Seed a working demo: admin reference data plus a set of runs in every state.

Gives a reviewer something to look at: aliases so attribute checks resolve, the three
example checks from the design doc, compliance rules, and runs sitting at each point in
the lifecycle — queued, needs review, finalized OK, finalized Not OK, and failed.

Everything is synthetic (ADR-003). Point it at a scratch database, not a real one.

Usage:
    DATABASE_URL=sqlite+pysqlite:///./data/demo.db GREENLIGHT_AI_DATA_DIR=./data \\
        python scripts/seed_demo.py
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Final, Sequence

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic_model import FIXTURE_ALIASES, build_client  # noqa: E402

import greenlight_ai.worker.runner as runner  # noqa: E402
from greenlight_ai.auth import accounts  # noqa: E402
from greenlight_ai.auth.passwords import hash_password  # noqa: E402
from greenlight_ai.db import catalog, models  # noqa: E402
from greenlight_ai.db.session import create_all, create_engine, session_factory  # noqa: E402
from greenlight_ai.parsers.reports.xlsx import parser_for  # noqa: E402
from greenlight_ai.config.store import write_setting  # noqa: E402
from greenlight_ai.db.settings import DbSettings  # noqa: E402
from greenlight_ai.db.types import utcnow  # noqa: E402
from greenlight_ai.llm.settings import LLMSettings  # noqa: E402

_LOG: Final = logging.getLogger("seed_demo")

#: The named values the design doc's three example checks refer to.
NAMED_VALUES: Final[list[dict[str, Any]]] = [
    {
        "name": "billing_count",
        "report_type": "billing",
        "sheet": "Summary",
        "locator": {"kind": "label", "label": "Billing count", "value_column": 1},
        "description": "Records billed to the customer for this order",
    },
    {
        "name": "delivered_count",
        "report_type": "billing",
        "sheet": "Summary",
        "locator": {"kind": "label", "label": "Delivered count", "value_column": 1},
        "description": "Records delivered in the number flow",
    },
    {
        "name": "accepts_count",
        "report_type": "counts",
        "sheet": "Flow",
        "locator": {"kind": "label", "label": "Accepts", "value_column": 3},
        "description": "Accepted records",
    },
    {
        "name": "rejects_count",
        "report_type": "counts",
        "sheet": "Flow",
        "locator": {"kind": "label", "label": "Rejects", "value_column": 3},
        "description": "Rejected records",
    },
    {
        "name": "input_count",
        "report_type": "counts",
        "sheet": "Flow",
        "locator": {"kind": "label", "label": "Input", "value_column": 3},
        "description": "Records entering the flow",
    },
]

#: The design doc's own examples.
CHECKS: Final[list[dict[str, Any]]] = [
    {
        "name": "billing_not_above_delivered",
        "expression": "billing_count <= delivered_count",
        "reasoning": "Billing count must not be more than the records delivered in the number "
        "flow report.",
        "severity": "high",
    },
    {
        "name": "billing_not_below_accepts",
        "expression": "billing_count >= accepts_count",
        "reasoning": "Billing count must not be less than the accepts count.",
        "severity": "high",
    },
    {
        "name": "counts_add_up",
        "expression": "accepts_count + rejects_count == input_count",
        "reasoning": "Every input record ends as an accept or a reject.",
        "severity": "high",
    },
]

COMPLIANCE: Final[list[dict[str, Any]]] = [
    {
        "name": "OFAC suppression",
        "path": "suppressions.ofac",
        "reasoning": "OFAC-listed consumers must be suppressed on every prescreen delivery.",
    },
    {
        "name": "Deceased suppression",
        "path": "suppressions.deceased",
        "reasoning": "Deceased consumers must be suppressed on every delivery.",
    },
    {
        "name": "Opt-out list applied",
        "path": "suppressions.optout",
        "reasoning": "Every prescreen delivery must apply the opt-out list.",
    },
]

#: Which fixture case each demo run uses, and where to leave it.
#:
#: Order matters. The worker claims the oldest queued job, so anything meant to stay
#: queued has to be submitted *after* every scenario that drives the worker; otherwise
#: the next scenario's worker call runs it.
SCENARIOS: Final[list[tuple[str, str, str]]] = [
    (
        "baseline_match",
        "finalize_ok",
        "Config and reports match the OSL; one compliance rule is not implemented.",
    ),
    (
        "geography_extra_state",
        "review",
        "The worked example: TX in the config, TX and NV delivered.",
    ),
    ("score_value_mismatch", "finalize_not_ok", "Score threshold 750 against a required 755."),
    ("counts_do_not_reconcile", "review", "588 records unaccounted for in the waterfall."),
    ("attributes_missing_in_report", "review", "A requested attribute was not delivered."),
    ("operator_boundary_drift", "review", "Same threshold, different boundary operator."),
    (
        "missing_waterfall_step",
        "failed",
        "Left failed so the error path is visible on the Runs screen.",
    ),
    ("rule_missing_in_config", "queued", "Left queued so the Runs screen shows a queue position."),
]


#: How a terminal run status reads in the summary.
LABELS: Final[dict[str, str]] = {
    "queued": "queued",
    "failed": "failed",
    "needs_review": "needs review",
    "finalized": "finalized",
}


def actual_status(factory: Any, run_id: int, expected: str) -> str:
    """Describe where a run really ended up, not where it was meant to.

    The seed used to record the outcome it asked for, so a run that never left the
    queue was still announced as finalized. Reading the row back means a broken
    scenario is visible in the summary instead of being discovered in the UI.

    Args:
        factory: A session factory.
        run_id: The run to read.
        expected: The DB status this scenario should have reached.

    Returns:
        A label for the summary, marked when it disagrees with ``expected``.
    """
    with factory() as session:
        run = session.get(models.Run, run_id)
        status = run.status if run is not None else "missing"
    if status == expected:
        return LABELS.get(status, status)
    return f"{status} (expected {expected})"


def make_due(factory: Any, run_id: int) -> None:
    """Clear the submission grace window so the next worker turn claims this run.

    A submitted run is enqueued with ``run_after = now + queue.grace_seconds``
    (`api/routers/runs.py`), which gives a person half a minute to notice a wrong
    file before any tokens are spent. The seed has no person and drives the worker
    by hand, so it brings the job forward; without this every ``run_once`` finds
    nothing due and the runs sit queued.

    Args:
        factory: A session factory.
        run_id: The run whose jobs become due.
    """
    with factory() as session:
        session.execute(
            sa.update(models.Job).where(models.Job.run_id == run_id).values(run_after=utcnow())
        )
        session.commit()


def seed_admin(session: Any, data_dir: Path, fixtures: Path, manifest: dict[str, Any]) -> None:
    """Load the reference data a working install would have.

    Args:
        session: An open session.
        data_dir: The shared volume.
        fixtures: The fixtures root.
        manifest: The decoded fixture manifest.
    """
    accounts.ensure_placeholder(session)
    if not session.execute(
        sa.select(models.User).where(models.User.username == "demoadmin")
    ).first():
        session.add(
            models.User(
                username="demoadmin",
                name="Dana Admin",
                email="demoadmin@example.com",
                password_hash=hash_password("demo-administrator"),
                roles=["user", "admin"],
            )
        )
    # A senior associate: a user *and* a reviewer (ADR-049). Seeded so the difference
    # between the three roles can be seen with login switched on, rather than only
    # read about — with it off this account is not reachable and changes nothing.
    if not session.execute(
        sa.select(models.User).where(models.User.username == "demoreviewer")
    ).first():
        session.add(
            models.User(
                username="demoreviewer",
                name="Robin Reviewer",
                email="demoreviewer@example.com",
                password_hash=hash_password("demo-reviewer-account"),
                roles=["user", "reviewer"],
            )
        )

    # ``canonical_by_alias`` maps alias to canonical, so the names read that way
    # round. Spelled backwards this looks like a transposition and is not.
    for alias, canonical in FIXTURE_ALIASES.canonical_by_alias.items():
        session.add(models.AttributeAlias(canonical_name=canonical, alias=alias))

    catalog.seed_defaults(session)

    baseline = next(c for c in manifest["cases"] if c["name"] == "baseline_match")
    template_dir = data_dir / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("billing", "counts", "dirt", "state_distribution", "field_distribution"):
        source = fixtures / baseline["reports"][kind]
        target = template_dir / f"{kind}.xlsx"
        target.write_bytes(source.read_bytes())
        row = session.execute(
            sa.select(models.ArtifactType).where(models.ArtifactType.key == kind)
        ).scalar_one()
        session.add(
            models.ArtifactSample(
                artifact_type_id=row.id,
                label="synthetic",
                filename=f"{kind}_sample.xlsx",
                storage_path=str(target.relative_to(data_dir)),
                notes="Synthetic sample, generated by scripts/generate_fixtures.py",
                sheets=[sheet.name for sheet in parser_for(kind).parse(target).sheets],
                uploaded_by="Dana Admin",
            )
        )

    # What a configured install looks like: two artifacts and one programme carry
    # guidance, the rest carry none, which is the state ADR-020 says must be harmless.
    dirt = session.execute(
        sa.select(models.ArtifactType).where(models.ArtifactType.key == "dirt")
    ).scalar_one()
    dirt.ai_context = (
        "Per-attribute fill rates and value counts. The sample tab is masked, so judge "
        "coverage from the statistics rather than from rows."
    )
    am = session.execute(
        sa.select(models.RunScope).where(models.RunScope.code == "AM")
    ).scalar_one()
    am.standing_instructions = (
        "Account Monitoring deliveries are recurring, so a requirement that names a "
        "refresh cadence matters as much as one that names an attribute."
    )

    for value in NAMED_VALUES:
        session.add(models.NamedValueRow(**value))

    for check in CHECKS:
        session.add(
            models.CheckDefinitionRow(
                name=check["name"],
                expression=check["expression"],
                reasoning=check["reasoning"],
                severity=check["severity"],
                is_active=True,
            )
        )

    for rule in COMPLIANCE:
        session.add(
            models.ComplianceRuleRow(
                name=rule["name"],
                requirement={"json_path_contains": rule["path"], "expected_value": True},
                reasoning=rule["reasoning"],
                is_active=True,
            )
        )
    session.flush()
    _LOG.info(
        "seeded %d aliases, 5 samples, %d named values, %d checks, %d compliance rules",
        len(FIXTURE_ALIASES.canonical_by_alias),
        len(NAMED_VALUES),
        len(CHECKS),
        len(COMPLIANCE),
    )


def seed_training(session: Any) -> None:
    """Show what Train AI mode looks like once people have used it (ADR-021).

    Turns the mode on and seeds the queue in every state an administrator will meet:
    observations waiting, one already synthesized into a draft candidate, one
    rejected with its reason, and one approved rule running in shadow. The mock model
    answers every stage with an empty shape on purpose, so a live "synthesize" in the
    demo produces nothing; the data here is what a real model would have produced.

    Args:
        session: An open session, after the runs exist.
    """
    write_setting(session, "training.enabled", True, actor="Dana Admin")

    runs = list(session.execute(sa.select(models.Run).order_by(models.Run.id)).scalars())
    first = runs[0] if runs else None
    run_id = first.id if first else None
    customer = first.customer_name if first else ""

    waiting = [
        models.TrainingObservation(
            run_id=run_id,
            author="John Doe",
            kind="field_constraint",
            anchors=[{"kind": "report_field", "artifact": "dirt", "field": "account_status"}],
            statement="Account status is never blank in the DIRT. A blank means the extract "
            "dropped it.",
            expectation="Every row has a value.",
            severity_hint="high",
            scope_hint="customer",
            customer_name=customer,
        ),
        models.TrainingObservation(
            run_id=run_id,
            author="John Doe",
            kind="reconciliation",
            anchors=[
                {"kind": "osl_section", "reference": "OSL section 4 Score"},
                {
                    "kind": "report_cell",
                    "artifact": "score_distribution",
                    "sheet": "Bands",
                    "cell": "B3",
                },
            ],
            statement="Clause 4.2 of the OSL is what the first score band in the score "
            "distribution answers to; the two should agree.",
            severity_hint="medium",
            scope_hint="global",
            customer_name=customer,
        ),
    ]
    session.add_all(waiting)

    synthesized = models.TrainingObservation(
        run_id=run_id,
        author="John Doe",
        kind="field_constraint",
        anchors=[{"kind": "report_field", "artifact": "dirt", "field": "score"}],
        statement="For account review the score is never below 300 or above 850.",
        severity_hint="medium",
        scope_hint="programme",
        customer_name=customer,
        scope_code="AM",
        status="synthesized",
    )
    session.add(synthesized)
    session.flush()

    draft = models.RuleCandidate(
        name="score_within_band",
        target_kind="field_constraint",
        body={
            "field": "score",
            "constraint": "range",
            "value": {"min": 300, "max": 850},
            "report_kinds": ["dirt"],
        },
        reasoning="Scores outside 300 to 850 are not valid for account review.",
        severity="medium",
        scope="programme:AM",
        source_observation_ids=[synthesized.id],
        status="draft",
        model_draft={"name": "score_within_band", "target_kind": "field_constraint"},
        model_used="demo",
        prompt_version="1",
        replay={
            "runs_examined": len(runs),
            "related_findings": 2,
            "previously_dismissed": 0,
            "note": "Counts related findings on recent finalized runs.",
        },
        created_by="Dana Admin",
    )
    session.add(draft)
    session.flush()
    synthesized.candidate_id = draft.id
    synthesized.synthesized_at = utcnow()

    rejected = models.TrainingObservation(
        run_id=run_id,
        author="John Doe",
        kind="note",
        statement="The billing report is always late on Fridays.",
        severity_hint="low",
        scope_hint="customer",
        customer_name=customer,
        status="rejected",
        status_note="This is about delivery timing, not the content of a delivery; the tool "
        "cannot check it.",
    )
    session.add(rejected)

    approved_obs = models.TrainingObservation(
        run_id=run_id,
        author="John Doe",
        kind="field_constraint",
        anchors=[{"kind": "report_field", "artifact": "dirt", "field": "state"}],
        statement="State is never blank.",
        severity_hint="high",
        scope_hint="customer",
        customer_name=customer,
        status="synthesized",
    )
    session.add(approved_obs)
    session.flush()
    approved = models.RuleCandidate(
        name="state_not_blank",
        target_kind="field_constraint",
        body={"field": "state", "constraint": "not_blank", "value": {}, "report_kinds": ["dirt"]},
        reasoning="State is never blank in a correct delivery.",
        severity="high",
        scope=customer or "all",
        source_observation_ids=[approved_obs.id],
        status="approved",
        model_used="demo",
        prompt_version="1",
        created_by="Dana Admin",
        decided_by="Dana Admin",
        decided_at=utcnow(),
    )
    session.add(approved)
    session.flush()
    approved_obs.candidate_id = approved.id
    approved_obs.synthesized_at = utcnow()

    rule = models.FieldConstraint(
        field="state",
        constraint="not_blank",
        value={},
        report_kinds=["dirt"],
        severity="high",
        reasoning="State is never blank in a correct delivery.",
        scope=customer or "all",
        state="shadow",
        origin="learned",
        candidate_id=approved.id,
        created_by="Dana Admin",
    )
    session.add(rule)
    session.flush()
    session.add(
        models.RuleStateChange(
            rule_kind="field_constraint",
            rule_id=rule.id,
            from_state="draft",
            to_state="shadow",
            note=f"approved from candidate {approved.id}",
            actor="Dana Admin",
        )
    )
    session.flush()
    # A standing note on the first run's configuration, so the queue shows a
    # configuration-specific comment and the next run of it carries the note (ADR-024).
    if first is not None:
        session.add(
            models.TrainingObservation(
                author="John Doe",
                kind="config_note",
                configuration_id=first.configuration_id,
                anchors=[{"kind": "config_path", "reference": first.configuration_id}],
                statement="This configuration excludes closed accounts by design; a missing "
                "closed-account count is not a gap.",
                severity_hint="medium",
                scope_hint="customer",
                customer_name=customer,
            )
        )
        session.flush()
    session.add_all(
        [
            models.ProgrammeRule(
                scope_code="AS",
                title="Opt-outs excluded",
                text="Every prescreen delivery excludes accounts that opted out of firm offers.",
                strictness="must",
                sort_order=10,
                scope="programme:AS",
                created_by="Dana Admin",
            ),
            models.ProgrammeRule(
                scope_code="AS",
                title="Score bands named as in the OSL",
                text="Score bands in the reports are named exactly as the OSL names them.",
                strictness="should",
                sort_order=20,
                scope="programme:AS",
                created_by="Dana Admin",
            ),
            models.ProgrammeRule(
                scope_code="AM",
                title="Refresh cadence stated",
                text="A monitoring delivery states its refresh cadence somewhere in the OSL.",
                strictness="advisory",
                sort_order=10,
                scope="programme:AM",
                created_by="Dana Admin",
            ),
        ]
    )
    session.flush()
    _LOG.info(
        "seeded the training queue: 5 observations, 2 candidates, 1 shadow rule, 3 programme rules"
    )


def seed_review_load(session: Any) -> int:
    """Show what the Review load screen looks like once people have used it (6.18a).

    The screen reads verdicts people gave, and a fresh install has none, so it opens
    empty and says nothing about itself. This seeds the three states an administrator
    needs to be able to tell apart, each built from *decided findings on real runs*
    rather than written straight into the signature table — so what appears is what the
    production path would have produced, and the arithmetic is exercised rather than
    asserted.

    Deliberately synthetic and deliberately not evidence. The real question — *it would
    have hidden these; was any of them real?* — needs real verdicts from real reviewers
    and is `docs/phase-7.1.md`.

    Args:
        session: An open session, after the runs exist.

    Returns:
        How many signature rows ended up in each state, as a count of rows written.
    """
    from greenlight_ai.training import signatures

    customer = "Northwind Credit Union"
    cases = [
        # (rule, element, severity, verdicts) — the three states, in order.
        ("check:12", "score_band", "low", ["false_positive"] * 10),
        ("check:12", "state_code", "low", ["false_positive"] * 4),
        ("check:31", "account_status", "medium", ["false_positive"] * 8 + ["confirmed"]),
        ("check:44", "credit_date", "high", ["false_positive"] * 12),
    ]

    written = 0
    for rule_ref, element_ref, severity, verdicts in cases:
        for index, verdict in enumerate(verdicts):
            run = models.Run(
                customer_name=customer,
                order_number=f"ORD-{rule_ref[-2:]}-{index:02d}",
                configuration_id="CFG-NWCU-AS",
                scope="AS",
                status="finalized",
            )
            session.add(run)
            session.flush()
            finding = models.Finding(
                run_id=run.id,
                finding_id="F-01",
                type="value_mismatch",
                severity=severity,
                title=f"{element_ref} did not match the configuration",
                detail="Seeded for the Review load screen.",
                leg="config_reports",
                rule_ref=rule_ref,
                element_ref=element_ref,
                review_status=verdict,
                reviewed_at=utcnow(),
                evidence={},
            )
            session.add(finding)
            session.flush()
            signatures.recompute_for_finding(session, finding)
        written += 1
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(description="Seed a demo database with runs and admin data.")
    parser.add_argument("--fixtures", type=Path, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    from fastapi.testclient import TestClient

    from greenlight_ai.api.app import create_app
    from greenlight_ai.worker.app import Worker

    runner.build_client = (  # type: ignore[assignment]
        lambda settings, cache=None, call_log=None, **kwargs: build_client(
            settings, cache=cache, call_log=call_log
        )
    )

    settings = DbSettings.from_env()
    engine = create_engine(settings)
    create_all(engine)
    factory = session_factory(engine)

    fixtures = args.fixtures or (settings.data_dir / "fixtures")
    if not (fixtures / "manifest.json").exists():
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent / "generate_fixtures.py"),
                "--out",
                str(fixtures),
                "--log-level",
                "ERROR",
            ],
            check=True,
        )
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))
    by_name = {case["name"]: case for case in manifest["cases"]}

    with factory() as session:
        if session.query(models.CheckDefinitionRow).count() == 0:
            seed_admin(session, settings.data_dir, fixtures, manifest)
            session.commit()

    app = create_app(settings, LLMSettings())
    app.state.session_factory = factory
    worker = Worker(factory, settings.data_dir, settings.is_sqlite, LLMSettings())
    created: list[tuple[int, str, str]] = []

    with TestClient(app) as client:
        for index, (case_name, outcome, note) in enumerate(SCENARIOS):
            case = by_name[case_name]
            files = [
                (
                    "osl",
                    ("osl.docx", (fixtures / case["osl"]).read_bytes(), "application/octet-stream"),
                ),
                (
                    "config",
                    ("config.json", (fixtures / case["config"]).read_bytes(), "application/json"),
                ),
            ]
            for kind, path in case["reports"].items():
                files.append(
                    (
                        kind,
                        (
                            f"{kind}.xlsx",
                            (fixtures / path).read_bytes(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        ),
                    )
                )

            response = client.post(
                "/api/v1/runs",
                data={
                    "customer_name": case["customer"],
                    "order_number": case["order_number"],
                    "configuration_id": case["configuration_id"],
                    "notes": note,
                    "rerun_reason": f"demo seed {index}",
                },
                files=files,
            )
            run_id = response.json().get("run_id")
            if run_id is None:
                continue

            if outcome == "queued":
                created.append((run_id, "queued", note))
                continue

            if outcome == "failed":
                # Remove an input so the run fails the way a real broken upload would.
                with factory() as session:
                    run = session.get(models.Run, run_id)
                    osl = next(f for f in run.files if f.kind == "osl")
                    (settings.data_dir / osl.storage_key).unlink(missing_ok=True)
                    session.commit()
                for _ in range(4):
                    make_due(factory, run_id)
                    worker.run_once()
                    with factory() as session:
                        if session.get(models.Run, run_id).status == "failed":
                            break
                created.append((run_id, actual_status(factory, run_id, "failed"), note))
                continue

            make_due(factory, run_id)
            worker.run_once()

            findings = client.get(f"/api/v1/runs/{run_id}/findings").json()
            if outcome == "finalize_ok":
                for finding in findings:
                    client.patch(
                        f"/api/v1/findings/{finding['id']}",
                        json={
                            "review_status": "false_positive",
                            "review_note": "Reviewed and accepted.",
                        },
                    )
                client.post(f"/api/v1/runs/{run_id}/finalize")
                created.append((run_id, actual_status(factory, run_id, "finalized") + " OK", note))
            elif outcome == "finalize_not_ok":
                for finding in findings:
                    if finding["severity"] == "high":
                        client.patch(
                            f"/api/v1/findings/{finding['id']}",
                            json={
                                "review_status": "confirmed",
                                "review_note": "Config must be corrected and the "
                                "file re-pulled. Ticket QC-2231.",
                            },
                        )
                    else:
                        client.patch(
                            f"/api/v1/findings/{finding['id']}",
                            json={
                                "review_status": "accepted_risk",
                                "review_note": "Known and accepted for this customer.",
                            },
                        )
                client.post(f"/api/v1/runs/{run_id}/finalize")
                created.append(
                    (run_id, actual_status(factory, run_id, "finalized") + " Not OK", note)
                )
            else:
                created.append((run_id, actual_status(factory, run_id, "needs_review"), note))

    print("")
    with factory() as session:
        seed_training(session)
        session.commit()

    with factory() as session:
        signature_rows = seed_review_load(session)
        session.commit()

    print(f"Seeded {len(created)} run(s) into {settings.url}")
    print("")
    for run_id, state, note in created:
        print(f"  VR-{run_id:04d}  {state:16}  {note}")
    print("")
    print(f"Review load: {signature_rows} finding signature(s) across watching, would-hide")
    print("  and blocked. Nothing is acted on; see docs/phase-7.1.md for the real question.")
    print("")
    print("Start the services:")
    print("  uvicorn greenlight_ai.api.app:get_app --factory --reload")
    print("  python -m greenlight_ai.worker.app")
    print("  cd user-ui && npm run dev      # :3000")
    print("  cd admin-ui && npm run dev     # :3001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
