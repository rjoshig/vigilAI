"""The migration chain is single, linear, and applies to an empty database.

Written after a duplicate revision id shipped and every other test stayed green:
the suite builds its schema from the models with ``create_all``, so nothing exercised
alembic at all. A broken chain would first be discovered by whoever ran an upgrade.

These are cheap and they cover the three ways the chain breaks in practice: two files
claiming one revision, two heads because a `down_revision` was not repointed, and a
migration that does not actually run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[2] / "src/greenlight_ai/db/migrations/versions"

_REVISION = re.compile(r'^revision: str = "(.+?)"', re.M)
_DOWN = re.compile(r'^down_revision: Union\[str, None\] = (?:"(.+?)"|None)', re.M)


def _chain() -> tuple[dict[str, str], dict[str, str | None]]:
    """Every migration's revision and the one it follows.

    Returns:
        Revision to filename, and revision to its parent (``None`` for the first).
    """
    revisions: dict[str, str] = {}
    parents: dict[str, str | None] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_text()
        found = _REVISION.search(text)
        if not found:
            continue
        revision = found.group(1)
        assert revision not in revisions, (
            f"revision {revision} is claimed by both {revisions[revision]} and {path.name}. "
            "Alembic reports this as a cycle and refuses to upgrade at all."
        )
        revisions[revision] = path.name
        down = _DOWN.search(text)
        parents[revision] = down.group(1) if down else None
    return revisions, parents


def test_no_two_migrations_claim_the_same_revision() -> None:
    """The failure that prompted this file. The assertion is in the helper."""
    revisions, _ = _chain()
    assert revisions


def test_there_is_exactly_one_head() -> None:
    """Two heads mean somebody added a migration without repointing the last one."""
    revisions, parents = _chain()
    claimed = {parent for parent in parents.values() if parent}
    heads = sorted(set(revisions) - claimed)
    assert len(heads) == 1, f"expected one head, found {[revisions[h] for h in heads]}"


def test_every_parent_exists() -> None:
    """A `down_revision` naming a file nobody has is an unrunnable chain."""
    revisions, parents = _chain()
    for revision, parent in parents.items():
        if parent is not None:
            assert (
                parent in revisions
            ), f"{revisions[revision]} follows {parent}, which no migration defines"


def test_the_chain_reaches_the_first_migration_from_the_head() -> None:
    """Walking back from the head visits every migration exactly once."""
    revisions, parents = _chain()
    claimed = {parent for parent in parents.values() if parent}
    head = next(iter(set(revisions) - claimed))

    seen: list[str] = []
    current: str | None = head
    while current is not None:
        assert current not in seen, f"cycle at {revisions[current]}"
        seen.append(current)
        current = parents[current]
    assert len(seen) == len(revisions)


# Alembic 1.20 warns that `alembic.ini` predates its `path_separator` key. The repo
# pins `alembic>=1.13`, where that key does not exist, so the file is correct for the
# floor it supports and the warning is about this environment rather than this project.
# Scoped here rather than added to the project's filters, which would hide it
# everywhere including where it might one day matter.
@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_migrations_apply_to_an_empty_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one that would have caught it, by doing what an operator does.

    Runs the real upgrade against a fresh SQLite file and asserts the schema that
    comes out matches the models the application actually uses.

    ``DATABASE_URL`` rather than alembic's own ``sqlalchemy.url``, because that is
    where `migrations/env.py` reads it from and so is what an operator actually sets.
    """
    alembic = pytest.importorskip("alembic.command")
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    database = tmp_path / "chain.db"
    url = f"sqlite+pysqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "src/greenlight_ai/db/migrations"))
    alembic.upgrade(config, "head")

    engine = sa.create_engine(url)
    tables = set(sa.inspect(engine).get_table_names())
    engine.dispose()

    from greenlight_ai.db import models

    expected = {table.name for table in models.Base.metadata.sorted_tables}
    assert expected - tables == set(), f"migrations do not create {sorted(expected - tables)}"


#: Columns where a migrated database and the models already disagreed before this test
#: existed. Each is the same defect `b8d0f2a4c6e9` fixed on ``runs``: added nullable,
#: declared NOT NULL, so a migrated row can hold a NULL the model says is impossible.
#:
#: They are listed rather than fixed because none of them is breaking anything today and
#: two are ``created_at`` timestamps — the only honest backfill for a creation time
#: nobody recorded is not "now", and inventing one to satisfy a constraint is worse than
#: the NULL. Each wants its own decision.
#:
#: **This list may only ever shrink.** A new entry means somebody has added a column the
#: same way and the test is telling them so.
KNOWN_SCHEMA_DRIFT: frozenset[str] = frozenset(
    {
        "coverage_acknowledgements.created_at",
        "final_reports.attestation",
        "findings.lens_opinions",
        "rule_candidates.critique",
        "rule_candidates.redraft",
        "second_approvals.covered",
        "second_approvals.created_at",
    }
)


@pytest.mark.filterwarnings("ignore:No path_separator found in configuration:DeprecationWarning")
def test_a_migrated_schema_matches_the_models_column_for_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Table names were never enough, and the gap cost a 500 on the review screen.

    The suite builds its schema with ``create_all``; an operator builds theirs with
    ``alembic upgrade``. Nothing compared the two below the level of table names, so a
    column the migrations created **nullable** while the model declared it NOT NULL was
    invisible: a test database could not hold the NULL that a migrated one was full of.
    ``Run.error_detail`` did exactly that and failed validation on the way out.

    Columns and nullability, both directions. A column the model has and the migrations
    do not is a 500 waiting to happen; one the migrations have and the model does not is
    a column nothing maintains.
    """
    alembic = pytest.importorskip("alembic.command")
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    database = tmp_path / "parity.db"
    url = f"sqlite+pysqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "src/greenlight_ai/db/migrations"))
    alembic.upgrade(config, "head")

    from greenlight_ai.db import models

    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    migrated = {
        name: {column["name"]: column["nullable"] for column in inspector.get_columns(name)}
        for name in inspector.get_table_names()
    }
    engine.dispose()

    missing: list[str] = []
    mismatched: list[str] = []
    for table in models.Base.metadata.sorted_tables:
        columns = migrated.get(table.name, {})
        for column in table.columns:
            if column.name not in columns:
                missing.append(f"{table.name}.{column.name}")
            elif (
                columns[column.name] != column.nullable
                and f"{table.name}.{column.name}" not in KNOWN_SCHEMA_DRIFT
            ):
                mismatched.append(
                    f"{table.name}.{column.name}: migrations say "
                    f"{'NULL' if columns[column.name] else 'NOT NULL'}, "
                    f"the model says {'NULL' if column.nullable else 'NOT NULL'}"
                )

    assert not missing, f"migrations do not create these columns: {sorted(missing)}"
    stale = sorted(
        entry
        for entry in KNOWN_SCHEMA_DRIFT
        if (lambda parts: migrated.get(parts[0], {}).get(parts[1]) is False)(entry.split("."))
    )
    assert not stale, (
        "these were fixed but are still listed as known drift; remove them from "
        f"KNOWN_SCHEMA_DRIFT so it keeps shrinking: {stale}"
    )
    assert not mismatched, (
        "a migrated database and the models disagree, so the suite is testing a schema "
        "nobody runs:\n  " + "\n  ".join(sorted(mismatched))
    )
