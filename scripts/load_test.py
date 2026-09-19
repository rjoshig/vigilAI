#!/usr/bin/env python3
"""A local load test: many runs through the real API and worker.

The design targets ~80 concurrent users and 5–15 minutes per run
(`docs/design.md` "Queueing, scale, and observability"). That cannot be reproduced on a
laptop — the real cost is the model, and here it is a scripted stand-in — so this
measures what a laptop *can* answer honestly:

- does the API stay responsive while workers churn,
- does the queue hand out each job exactly once with several workers running,
- does the per-order-number cap hold under concurrent submission,
- how long the code-only stages take, which is the part that does not change in-house.

It does **not** predict production throughput. That needs the real model behind it, and
the result belongs in `docs/benchmarks/`.

Usage:
    python scripts/load_test.py --runs 20 --workers 4
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Final, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic_model import FIXTURE_ALIASES, build_client  # noqa: E402

import vigilai.worker.runner as runner  # noqa: E402
from vigilai.db import models  # noqa: E402
from vigilai.db.session import create_all, create_engine, session_factory  # noqa: E402
from vigilai.db.settings import DbSettings  # noqa: E402
from vigilai.llm.settings import LLMSettings  # noqa: E402
from vigilai.worker.app import Worker  # noqa: E402

_LOG: Final = logging.getLogger("load_test")


def _install_stand_in_model() -> None:
    """Point the worker at the scripted model instead of a real one."""
    runner.build_client = (  # type: ignore[assignment]
        lambda settings, cache=None, call_log=None, **kwargs: build_client(
            settings, cache=cache, call_log=call_log
        )
    )


def _submit(client: Any, case: dict[str, Any], root: Path, order: str, reason: str) -> Any:
    """Submit one run through the real multipart endpoint."""
    files = [
        ("osl", ("osl.docx", (root / case["osl"]).read_bytes(), "application/octet-stream")),
        ("config", ("config.json", (root / case["config"]).read_bytes(), "application/json")),
    ]
    for kind, path in case["reports"].items():
        files.append(
            (
                kind,
                (
                    f"{kind}.xlsx",
                    (root / path).read_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        )
    data = {
        "customer_name": case["customer"],
        "order_number": order,
        "configuration_id": case["configuration_id"],
        "rerun_reason": reason,
    }
    return client.post("/api/v1/runs", data=data, files=files)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments.

    Returns:
        ``0`` when every submitted run completed, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description="Load-test the API and the workers locally.")
    parser.add_argument("--runs", type=int, default=20, help="How many runs to submit.")
    parser.add_argument("--workers", type=int, default=4, help="How many worker threads.")
    parser.add_argument("--fixtures", type=Path, default=None, help="An existing fixtures root.")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    import json
    import subprocess

    from fastapi.testclient import TestClient

    from vigilai.api.app import create_app

    _install_stand_in_model()

    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        root = args.fixtures
        if root is None:
            root = workspace / "fixtures"
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parent / "generate_fixtures.py"),
                    "--out",
                    str(root),
                    "--log-level",
                    "ERROR",
                ],
                check=True,
            )
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        cases = manifest["cases"]

        settings = DbSettings(
            url=f"sqlite+pysqlite:///{workspace / 'load.db'}", data_dir=workspace / "data"
        )
        engine = create_engine(settings)
        create_all(engine)
        factory = session_factory(engine)
        app = create_app(settings, LLMSettings())
        app.state.session_factory = factory

        with factory() as session:
            for canonical, alias in FIXTURE_ALIASES.canonical_by_alias.items():
                session.add(models.AttributeAlias(canonical_name=alias, alias=canonical))
            session.commit()

        submit_times: list[float] = []
        accepted = 0
        capped = 0

        print(f"Submitting {args.runs} run(s)…")
        with TestClient(app) as client:
            for index in range(args.runs):
                case = cases[index % len(cases)]
                started = time.monotonic()
                response = _submit(client, case, root, f"LOAD-{index:04d}", f"load test {index}")
                submit_times.append((time.monotonic() - started) * 1000)
                if response.status_code == 201:
                    accepted += 1
                elif response.status_code == 409:
                    capped += 1

            print(f"Accepted {accepted}, capped {capped}. Running {args.workers} worker(s)…")

            processed: list[int] = []
            lock = threading.Lock()

            def drain() -> None:
                worker = Worker(factory, settings.data_dir, True, LLMSettings())
                count = 0
                while worker.run_once():
                    count += 1
                with lock:
                    processed.append(count)

            wall_start = time.monotonic()
            threads = [threading.Thread(target=drain) for _ in range(args.workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            wall = time.monotonic() - wall_start

            with factory() as session:
                statuses = dict(
                    session.execute(
                        __import__("sqlalchemy")
                        .select(models.Run.status, __import__("sqlalchemy").func.count())
                        .group_by(models.Run.status)
                    ).all()
                )
                durations = [
                    int(row)
                    for row in session.execute(
                        __import__("sqlalchemy")
                        .select(__import__("sqlalchemy").func.sum(models.RunStage.duration_ms))
                        .group_by(models.RunStage.run_id)
                    ).scalars()
                ]

        done = statuses.get("needs_review", 0)
        print("")
        print(f"Wall clock:        {wall:.1f}s for {sum(processed)} job(s)")
        print(f"Jobs per worker:   {sorted(processed, reverse=True)}")
        print(f"Run statuses:      {statuses}")
        if durations:
            print(
                f"Pipeline p50/p95:  {statistics.median(durations):.0f} ms / "
                f"{sorted(durations)[int(0.95 * (len(durations) - 1))]:.0f} ms"
            )
        print(
            f"Submit p50/p95:    {statistics.median(submit_times):.0f} ms / "
            f"{sorted(submit_times)[int(0.95 * (len(submit_times) - 1))]:.0f} ms"
        )
        print("")
        print(
            "The model here is a scripted stand-in, so these timings measure the code "
            "paths, not production throughput."
        )

        return 0 if done == accepted else 1


if __name__ == "__main__":
    sys.exit(main())
