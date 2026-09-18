#!/usr/bin/env python3
"""Seed a working demo: admin reference data plus a set of runs in every state.

Gives a reviewer something to look at: aliases so attribute checks resolve, the three
example checks from the design doc, compliance rules, and runs sitting at each point in
the lifecycle — queued, needs review, finalized OK, finalized Not OK, and failed.

Everything is synthetic (ADR-003). Point it at a scratch database, not a real one.

Usage:
    DATABASE_URL=sqlite+pysqlite:///./data/demo.db VIGILAI_DATA_DIR=./data \\
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic_model import FIXTURE_ALIASES, build_client  # noqa: E402

import vigilai.worker.runner as runner  # noqa: E402
from vigilai.db import models  # noqa: E402
from vigilai.db.session import create_all, create_engine, session_factory  # noqa: E402
from vigilai.db.settings import DbSettings  # noqa: E402
from vigilai.llm.settings import LLMSettings  # noqa: E402

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


def seed_admin(session: Any, data_dir: Path, fixtures: Path, manifest: dict[str, Any]) -> None:
    """Load the reference data a working install would have.

    Args:
        session: An open session.
        data_dir: The shared volume.
        fixtures: The fixtures root.
        manifest: The decoded fixture manifest.
    """
    for canonical, alias in FIXTURE_ALIASES.canonical_by_alias.items():
        session.add(models.AttributeAlias(canonical_name=alias, alias=canonical))

    baseline = next(c for c in manifest["cases"] if c["name"] == "baseline_match")
    template_dir = data_dir / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("billing", "counts", "dirt", "state_distribution", "field_distribution"):
        source = fixtures / baseline["reports"][kind]
        target = template_dir / f"{kind}.xlsx"
        target.write_bytes(source.read_bytes())
        session.add(
            models.ReportTemplate(
                report_type=kind,
                filename=f"{kind}_sample.xlsx",
                storage_path=str(target.relative_to(data_dir)),
                notes="Synthetic sample, generated by scripts/generate_fixtures.py",
            )
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
        "seeded %d aliases, 5 templates, %d named values, %d checks, %d compliance rules",
        len(FIXTURE_ALIASES.canonical_by_alias),
        len(NAMED_VALUES),
        len(CHECKS),
        len(COMPLIANCE),
    )


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

    from vigilai.api.app import create_app
    from vigilai.worker.app import Worker

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
                    worker.run_once()
                    with factory() as session:
                        if session.get(models.Run, run_id).status == "failed":
                            break
                        session.execute(
                            __import__("sqlalchemy")
                            .update(models.Job)
                            .where(models.Job.run_id == run_id)
                            .values(
                                run_after=__import__(
                                    "vigilai.db.types", fromlist=["utcnow"]
                                ).utcnow()
                            )
                        )
                        session.commit()
                created.append((run_id, "failed", note))
                continue

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
                created.append((run_id, "finalized OK", note))
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
                created.append((run_id, "finalized Not OK", note))
            else:
                created.append((run_id, "needs review", note))

    print("")
    print(f"Seeded {len(created)} run(s) into {settings.url}")
    print("")
    for run_id, state, note in created:
        print(f"  VR-{run_id:04d}  {state:16}  {note}")
    print("")
    print("Start the services:")
    print("  uvicorn vigilai.api.app:get_app --factory --reload")
    print("  python -m vigilai.worker.app")
    print("  cd user-ui && npm run dev      # :3000")
    print("  cd admin-ui && npm run dev     # :3001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
