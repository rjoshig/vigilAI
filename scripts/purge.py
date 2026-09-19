#!/usr/bin/env python3
"""Delete runs past their retention window, with their files.

Runs expire 90 days after creation (`docs/design.md` "Data model"). The purge deletes
the run, its uploaded files on the shared volume, and its rules, traces, and findings.
Aggregated usage survives: `llm_calls` rows are kept with their run reference cleared,
so the admin dashboard still has history after the runs behind it are gone.

Always dry-run first. Deleting a frozen report is not recoverable.

Usage:
    python scripts/purge.py --dry-run
    python scripts/purge.py
    python scripts/purge.py --older-than-days 30 --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from typing import Final, Sequence

import sqlalchemy as sa

from greenlight_ai.db import models, repository, versions
from greenlight_ai.db.session import create_engine, session_factory, session_scope
from greenlight_ai.db.settings import DbSettings
from greenlight_ai.db.types import utcnow

#: Where sample workbooks live under the data directory (``api/routers/admin.py``).
TEMPLATE_DIR: Final[str] = "templates"

_LOG: Final = logging.getLogger("purge")


def expired_runs(session: sa.orm.Session, cutoff: dt.datetime) -> list[models.Run]:
    """Find the runs a purge would delete.

    Args:
        session: An open session.
        cutoff: Runs expiring before this are in scope.

    Returns:
        The runs, oldest first.
    """
    return list(
        session.execute(
            sa.select(models.Run)
            .where(models.Run.expires_at.is_not(None), models.Run.expires_at < cutoff)
            .order_by(models.Run.expires_at)
        ).scalars()
    )


def describe(runs: Sequence[models.Run], data_dir: Path) -> str:
    """Render what a purge would do.

    Args:
        runs: The runs in scope.
        data_dir: The shared volume.

    Returns:
        A report naming each run, its age, and how many files go with it.
    """
    if not runs:
        return "Nothing has expired."

    lines = [f"{len(runs)} run(s) would be purged:", ""]
    total_bytes = 0
    for run in runs:
        sizes = [
            (data_dir / file.storage_key).stat().st_size
            for file in run.files
            if (data_dir / file.storage_key).exists()
        ]
        total_bytes += sum(sizes)
        lines.append(
            f"  VR-{run.id:04d}  {run.customer_name} · {run.order_number}  "
            f"expired {run.expires_at:%Y-%m-%d}  {len(run.files)} file(s)  "
            f"{sum(sizes) / 1024:.0f} KB"
        )
    lines += ["", f"Total on disk: {total_bytes / (1024 * 1024):.1f} MB"]
    lines.append("Aggregated usage statistics are kept; only the runs and their files go.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments.

    Returns:
        ``0`` always, so a nightly cron does not alarm on "nothing to do".
    """
    parser = argparse.ArgumentParser(description="Purge expired runs and their files.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted and change nothing. Do this first.",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help=(
            "Override the stored expiry and purge anything created more than this many "
            "days ago. For a one-off cleanup; the nightly job uses runs.expires_at."
        ),
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    settings = DbSettings.from_env()
    engine = create_engine(settings)
    factory = session_factory(engine)

    with session_scope(factory) as session:
        if args.older_than_days is not None:
            cutoff = utcnow()
            horizon = cutoff - dt.timedelta(days=args.older_than_days)
            session.execute(
                sa.update(models.Run)
                .where(models.Run.created_at < horizon)
                .values(expires_at=cutoff - dt.timedelta(seconds=1))
            )
            session.flush()

        runs = expired_runs(session, utcnow())
        print(describe(runs, settings.data_dir))

        if args.dry_run:
            print("\nDry run: nothing was deleted.")
            session.rollback()
            return 0

        if not runs:
            pruned = versions.prune_versions(session)
            orphans = versions.remove_orphan_samples(session, settings.data_dir, TEMPLATE_DIR)
            print(f"Pruned {pruned} version(s); removed {orphans} orphaned sample file(s).")
            return 0

        purged = repository.purge_expired(session, settings.data_dir)
        pruned = versions.prune_versions(session)
        orphans = versions.remove_orphan_samples(session, settings.data_dir, TEMPLATE_DIR)
        print(f"\nPurged {purged} run(s); pruned {pruned} version(s); removed {orphans} file(s).")
        _LOG.info("purge complete: %d run(s), %d version(s)", purged, pruned)

    return 0


if __name__ == "__main__":
    sys.exit(main())
